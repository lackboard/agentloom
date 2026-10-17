import asyncio
import sqlite3
import time
from uuid import uuid4

from fastapi.testclient import TestClient
from pydantic import PrivateAttr

from agentloom.api import create_app
from agentloom.config import AppConfig
from agentloom.models.fake import OfflineChatModel
from agentloom.persistence.database import create_sessionmaker, migrate_database
from agentloom.runtime.manager import RunManager, ThreadBusy


class CountingOfflineModel(OfflineChatModel):
    """记录真实模型边界被调用的次数。"""

    _calls: int = PrivateAttr(default=0)

    @property
    def calls(self) -> int:
        return self._calls

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self._calls += 1
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def test_http_idempotency_conflict_and_durable_input(tmp_path) -> None:
    model = CountingOfflineModel()
    app = create_app(tmp_path, config=AppConfig(), model=model)
    with TestClient(app) as client:
        thread = client.post("/api/threads", json={}).json()
        url = f"/api/threads/{thread['thread_id']}/runs"
        request_id = str(uuid4())
        body = {"text": "请计算 2 + 3", "attachment_ids": [], "client_request_id": request_id}
        first = client.post(url, json=body)
        repeat = client.post(url, json=body)
        changed = client.post(url, json={**body, "text": "different"})
        attachment = client.post(url, json={**body, "attachment_ids": ["file-1"]})

        assert first.status_code == repeat.status_code == 202
        assert first.json()["run_id"] == repeat.json()["run_id"]
        assert changed.status_code == 409 and changed.json()["error"]["code"] == "REQUEST_CONFLICT"
        assert attachment.status_code == 422
        assert client.get("/api/threads/missing/messages").status_code == 404
        for _ in range(100):
            run = client.get(f"/api/runs/{first.json()['run_id']}").json()
            if run["status"] == "succeeded":
                break
            time.sleep(0.01)
        assert run["status"] == "succeeded"
        assert model.calls == 2
        # 已完成后重发同一请求仍返回原 Run，且不会再进入模型。
        completed_repeat = client.post(url, json=body)
        assert completed_repeat.status_code == 202
        assert completed_repeat.json()["run_id"] == first.json()["run_id"]
        time.sleep(0.05)
        assert model.calls == 2
        messages = client.get(f"/api/threads/{thread['thread_id']}/messages").json()["items"]
        assert len(messages) == 4 and messages[0]["content"]["text"] == body["text"]
        assert messages[-1]["role"] == "assistant" and "最终答案：5" in messages[-1]["content"]["text"]
        assert messages[0]["id"]
        assert (tmp_path / "app.sqlite").exists() and (tmp_path / "checkpoints.sqlite").exists()
        with sqlite3.connect(tmp_path / "app.sqlite") as connection:
            assert connection.execute("SELECT COUNT(*) FROM runs").fetchone() == (1,)
            assert connection.execute("SELECT COUNT(*) FROM run_events").fetchone()[0] > 1
            assert connection.execute("SELECT input_message_id FROM runs").fetchone() == (messages[0]["id"],)

    with TestClient(create_app(tmp_path, config=AppConfig())) as restarted:
        assert restarted.get(f"/api/runs/{first.json()['run_id']}").json()["status"] == "succeeded"
        assert len(restarted.get(f"/api/threads/{thread['thread_id']}/messages").json()["items"]) == 4
        assert restarted.post(url, json=body).json()["run_id"] == first.json()["run_id"]


def test_concurrent_different_requests_get_only_one_thread_slot(tmp_path) -> None:
    app_path = tmp_path / "app.sqlite"
    migrate_database(app_path)

    async def scenario():
        sessions = create_sessionmaker(app_path)
        manager = RunManager(sessions, model_name="test-model")
        try:
            thread = await manager.create_thread()
            other = await manager.create_thread()

            async def submit(text):
                try:
                    return await manager.submit(thread.id, text=text, client_request_id=str(uuid4()))
                except ThreadBusy:
                    return "busy"

            results = await asyncio.gather(submit("one"), submit("two"))
            assert sum(result == "busy" for result in results) == 1
            assert sum(result != "busy" for result in results) == 1
            assert len(await manager.get_messages(thread.id)) == 1
            assert (await manager.submit(other.id, text="three", client_request_id=str(uuid4()))).status == "pending"
            third = await manager.create_thread()
            same_id = str(uuid4())
            duplicates = await asyncio.gather(
                manager.submit(third.id, text="same", client_request_id=same_id),
                manager.submit(third.id, text="same", client_request_id=same_id),
            )
            assert duplicates[0].id == duplicates[1].id
            assert len(await manager.get_messages(third.id)) == 1
            assert len(await manager.get_events(duplicates[0].id)) == 1
        finally:
            await sessions.kw["bind"].dispose()

    asyncio.run(scenario())
