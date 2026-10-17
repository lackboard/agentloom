import asyncio
import sqlite3
import time
from collections.abc import Sequence
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
from pydantic import PrivateAttr

from agentloom.api import create_app
from agentloom.config import AppConfig
from agentloom.models.fake import OfflineChatModel
from agentloom.persistence.database import create_sessionmaker, migrate_database
from agentloom.runtime.ledger import ToolCallConflict, ToolLedgerService, deserialize_tool_result
from agentloom.runtime.manager import RunManager


class ReplaceBatchModel(OfflineChatModel):
    """固定提出一个需审批覆盖和一个普通新建，便于观察整批暂停。"""

    _expected_sha256: str = PrivateAttr()

    def __init__(self, expected_sha256: str) -> None:
        super().__init__()
        self._expected_sha256 = expected_sha256

    def _respond(self, messages: Sequence[AnyMessage]) -> AIMessage:
        if isinstance(messages[-1], HumanMessage):
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "replace_file",
                        "args": {
                            "path": "/mnt/user-data/workspace/note.txt",
                            "old": "第一版",
                            "new": "第二版",
                            "expected_sha256": self._expected_sha256,
                        },
                        "id": "replace-call-1",
                        "type": "tool_call",
                    },
                    {
                        "name": "write_file",
                        "args": {
                            "path": "/mnt/user-data/outputs/side.txt",
                            "content": "普通工具也必须等待审批",
                        },
                        "id": "write-call-1",
                        "type": "tool_call",
                    },
                ],
                usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            )
        if isinstance(messages[-1], ToolMessage):
            return AIMessage(
                content="工具批次已经得到明确结果。",
                usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            )
        raise TypeError("测试模型只处理 HumanMessage 或 ToolMessage")


def _wait_status(client: TestClient, run_id: str, expected: set[str]) -> dict:
    result = {}
    for _ in range(300):
        result = client.get(f"/api/runs/{run_id}").json()
        if result.get("status") in expected:
            return result
        time.sleep(0.01)
    raise AssertionError(f"Run 未进入预期状态：{result}")


def _prepare_thread(client: TestClient) -> tuple[str, str]:
    thread_id = client.post("/api/threads", json={}).json()["thread_id"]
    file = client.app.state.workspace.write_text(
        thread_id,
        "/mnt/user-data/workspace/note.txt",
        "第一版",
    )
    return thread_id, file.sha256


def test_tool_ledger_replays_result_and_rejects_changed_arguments(tmp_path) -> None:
    app_path = tmp_path / "app.sqlite"
    migrate_database(app_path)

    async def scenario() -> None:
        sessions = create_sessionmaker(app_path)
        try:
            manager = RunManager(sessions, model_name="fake")
            thread = await manager.create_thread()
            run = await manager.submit(thread.id, text="ledger", client_request_id=str(uuid4()))
            ledger = ToolLedgerService(sessions)
            prepared = await ledger.prepare(run.id, "call-1", "add", {"a": 2, "b": 3})
            assert prepared.status == "prepared"
            running = await ledger.begin(prepared.id)
            assert running.status == "running" and running.attempts == 1
            message = ToolMessage(content="5", tool_call_id="call-1", name="add")
            completed = await ledger.finish(prepared.id, message)
            assert completed.status == "succeeded"

            replay = await ledger.prepare(run.id, "call-1", "add", {"a": 2, "b": 3})
            assert replay.status == "succeeded" and replay.attempts == 1
            restored = deserialize_tool_result(replay.result or {})
            assert isinstance(restored, ToolMessage) and restored.content == "5"
            with pytest.raises(ToolCallConflict):
                await ledger.prepare(run.id, "call-1", "add", {"a": 20, "b": 30})
        finally:
            await sessions.kw["bind"].dispose()

    asyncio.run(scenario())


def test_approval_survives_restart_and_resolution_is_idempotent(tmp_path) -> None:
    config = AppConfig()
    first_app = create_app(tmp_path, config=config, model=OfflineChatModel())
    with TestClient(first_app) as first_client:
        thread_id, old_sha = _prepare_thread(first_client)
        # 使用知道旧 hash 的确定性模型重新建立应用，只影响随后提交的 Run。
    first_app = create_app(tmp_path, config=config, model=ReplaceBatchModel(old_sha))
    with TestClient(first_app) as first_client:
        submitted = first_client.post(
            f"/api/threads/{thread_id}/runs",
            json={"text": "覆盖文件", "attachment_ids": [], "client_request_id": str(uuid4())},
        )
        run_id = submitted.json()["run_id"]
        waiting = _wait_status(first_client, run_id, {"waiting_input"})
        approval_id = waiting["pending_approval_id"]
        approval = first_client.get(f"/api/runs/{run_id}/approvals").json()["items"][0]
        assert approval["approval_id"] == approval_id and approval["checkpoint_ready"] is True
        assert (
            first_client.app.state.workspace.read_text(thread_id, "/mnt/user-data/workspace/note.txt").content
            == "第一版"
        )
        assert not (first_client.app.state.workspace.thread_root(thread_id) / "outputs" / "side.txt").exists()

    restarted_app = create_app(tmp_path, config=config, model=ReplaceBatchModel(old_sha))
    with TestClient(restarted_app) as restarted:
        body = {"payload_hash": approval["payload_hash"], "decision": "approve", "reason": None}
        accepted = restarted.post(f"/api/approvals/{approval_id}/resolve", json=body)
        repeated = restarted.post(f"/api/approvals/{approval_id}/resolve", json=body)
        conflict = restarted.post(
            f"/api/approvals/{approval_id}/resolve",
            json={**body, "decision": "reject"},
        )
        changed_payload = restarted.post(
            f"/api/approvals/{approval_id}/resolve",
            json={**body, "payload_hash": "0" * 64},
        )
        assert accepted.status_code == repeated.status_code == 200
        assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "APPROVAL_CONFLICT"
        assert changed_payload.status_code == 409
        assert _wait_status(restarted, run_id, {"succeeded"})["status"] == "succeeded"
        workspace = restarted.app.state.workspace
        assert workspace.read_text(thread_id, "/mnt/user-data/workspace/note.txt").content == "第二版"
        assert workspace.read_text(thread_id, "/mnt/user-data/outputs/side.txt").content == "普通工具也必须等待审批"
        ledger = restarted.get(f"/api/runs/{run_id}/tool-executions").json()["items"]
        assert {item["tool_name"]: (item["status"], item["attempts"]) for item in ledger} == {
            "replace_file": ("succeeded", 1),
            "write_file": ("succeeded", 1),
        }


def test_changed_file_invalidates_approved_replace(tmp_path) -> None:
    config = AppConfig()
    bootstrap = create_app(tmp_path, config=config, model=OfflineChatModel())
    with TestClient(bootstrap) as client:
        thread_id, old_sha = _prepare_thread(client)

    app = create_app(tmp_path, config=config, model=ReplaceBatchModel(old_sha))
    with TestClient(app) as client:
        run_id = client.post(
            f"/api/threads/{thread_id}/runs",
            json={"text": "覆盖文件", "attachment_ids": [], "client_request_id": str(uuid4())},
        ).json()["run_id"]
        waiting = _wait_status(client, run_id, {"waiting_input"})
        approval_id = waiting["pending_approval_id"]
        approval = client.get(f"/api/runs/{run_id}/approvals").json()["items"][0]

        captured = []
        original_resume = app.state.executor.resume
        app.state.executor.resume = captured.append
        response = client.post(
            f"/api/approvals/{approval_id}/resolve",
            json={"payload_hash": approval["payload_hash"], "decision": "approve", "reason": None},
        )
        assert response.status_code == 200 and len(captured) == 1
        changed = app.state.workspace.replace_text(
            thread_id,
            "/mnt/user-data/workspace/note.txt",
            old="第一版",
            new="外部修改",
            expected_sha256=old_sha,
        )
        app.state.executor.resume = original_resume
        client.portal.call(original_resume, captured[0])

        assert _wait_status(client, run_id, {"succeeded"})["status"] == "succeeded"
        assert app.state.workspace.read_text(thread_id, "/mnt/user-data/workspace/note.txt").sha256 == changed.sha256
        ledger = client.get(f"/api/runs/{run_id}/tool-executions").json()["items"]
        replacement = next(item for item in ledger if item["tool_name"] == "replace_file")
        assert replacement["status"] == "failed"
        assert replacement["error_code"] == "APPROVAL_PRECONDITION_FAILED"
        final_approval = client.get(f"/api/runs/{run_id}/approvals").json()["items"][0]
        assert final_approval["status"] == "approved" and final_approval["consumed_at"] is not None


def test_rejected_batch_executes_no_tools_and_pairs_every_call(tmp_path) -> None:
    config = AppConfig()
    bootstrap = create_app(tmp_path, config=config, model=OfflineChatModel())
    with TestClient(bootstrap) as client:
        thread_id, old_sha = _prepare_thread(client)

    app = create_app(tmp_path, config=config, model=ReplaceBatchModel(old_sha))
    with TestClient(app) as client:
        run_id = client.post(
            f"/api/threads/{thread_id}/runs",
            json={"text": "拒绝覆盖", "attachment_ids": [], "client_request_id": str(uuid4())},
        ).json()["run_id"]
        waiting = _wait_status(client, run_id, {"waiting_input"})
        approval = client.get(f"/api/runs/{run_id}/approvals").json()["items"][0]
        rejected = client.post(
            f"/api/approvals/{waiting['pending_approval_id']}/resolve",
            json={
                "payload_hash": approval["payload_hash"],
                "decision": "reject",
                "reason": "本次不允许覆盖",
            },
        )
        assert rejected.status_code == 200
        assert _wait_status(client, run_id, {"succeeded"})["status"] == "succeeded"
        workspace = app.state.workspace
        assert workspace.read_text(thread_id, "/mnt/user-data/workspace/note.txt").content == "第一版"
        assert not (workspace.thread_root(thread_id) / "outputs" / "side.txt").exists()
        ledger = client.get(f"/api/runs/{run_id}/tool-executions").json()["items"]
        assert {(item["tool_name"], item["status"], item["attempts"]) for item in ledger} == {
            ("replace_file", "denied", 0),
            ("write_file", "denied", 0),
        }
        messages = client.get(f"/api/threads/{thread_id}/messages").json()["items"]
        tool_messages = [item for item in messages if item["role"] == "tool"]
        assert {item["content"]["tool_call_id"] for item in tool_messages} == {
            "replace-call-1",
            "write-call-1",
        }
        with sqlite3.connect(tmp_path / "app.sqlite") as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM run_events WHERE run_id=? AND event_type LIKE 'tool.%'",
                (run_id,),
            ).fetchone() == (0,)
