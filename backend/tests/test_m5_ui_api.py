import time
from uuid import uuid4

from fastapi.testclient import TestClient
from langchain_core.messages import HumanMessage
from pydantic import PrivateAttr

from agentloom.api import create_app
from agentloom.config import AppConfig
from agentloom.models.fake import OfflineChatModel


class AttachmentObservingModel(OfflineChatModel):
    """记录模型实际收到的用户输入，证明附件不是只停留在页面或数据库。"""

    _human_inputs: list[str] = PrivateAttr(default_factory=list)

    @property
    def human_inputs(self) -> list[str]:
        return self._human_inputs

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        latest = next((message for message in reversed(messages) if isinstance(message, HumanMessage)), None)
        if latest is not None:
            self._human_inputs.append(str(latest.content))
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def test_workbench_restoration_and_attachment_context(tmp_path) -> None:
    model = AttachmentObservingModel()
    with TestClient(create_app(tmp_path, config=AppConfig(), model=model)) as client:
        thread_id = client.post("/api/threads", json={"title": "销售分析"}).json()["thread_id"]
        other_thread_id = client.post("/api/threads", json={"title": "另一个任务"}).json()["thread_id"]
        upload = client.post(
            f"/api/threads/{thread_id}/uploads",
            files={"file": ("sales.csv", b"month,amount\nJan,42\n", "text/csv")},
        )
        assert upload.status_code == 201
        artifact = upload.json()
        assert artifact["content_url"].endswith("/content")

        rejected = client.post(
            f"/api/threads/{other_thread_id}/runs",
            json={
                "text": "读取附件",
                "attachment_ids": [artifact["artifact_id"]],
                "client_request_id": str(uuid4()),
            },
        )
        assert rejected.status_code == 422
        assert rejected.json()["error"]["code"] == "ATTACHMENT_NOT_FOUND"

        submitted = client.post(
            f"/api/threads/{thread_id}/runs",
            json={
                "text": "分析这个文件",
                "attachment_ids": [artifact["artifact_id"]],
                "client_request_id": str(uuid4()),
            },
        )
        assert submitted.status_code == 202
        run_id = submitted.json()["run_id"]
        for _ in range(200):
            run = client.get(f"/api/runs/{run_id}").json()
            if run["status"] in {"succeeded", "failed", "cancelled"}:
                break
            time.sleep(0.01)
        assert run["status"] == "succeeded"

        listed = client.get("/api/threads").json()["items"]
        current = next(item for item in listed if item["thread_id"] == thread_id)
        assert current["latest_run"]["run_id"] == run_id
        detail = client.get(f"/api/threads/{thread_id}").json()
        assert detail["latest_run"]["status"] == "succeeded"
        assert isinstance(detail["todos"], list)

        messages = client.get(f"/api/threads/{thread_id}/messages").json()["items"]
        assert messages[0]["content"]["attachment_ids"] == [artifact["artifact_id"]]
        assert any("sales.csv" in content and "/mnt/user-data/uploads/" in content for content in model.human_inputs)
        files = client.get(f"/api/threads/{thread_id}/artifacts").json()["items"]
        assert files[0]["artifact_id"] == artifact["artifact_id"]
        assert client.get(f"/api/runs/{run_id}/subagents").json() == {"items": []}
