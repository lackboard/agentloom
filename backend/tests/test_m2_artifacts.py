import asyncio
import json
import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agentloom.api import create_app
from agentloom.artifacts import ArtifactNotFound, ArtifactService
from agentloom.config import AppConfig
from agentloom.models.fake import OfflineChatModel
from agentloom.persistence.database import create_sessionmaker, migrate_database
from agentloom.runtime.manager import RunManager
from agentloom.sandbox import WorkspaceError, WorkspaceService

OUTPUT_PATH = "/mnt/user-data/outputs/report.txt"
OUTPUT_CONTENT = "AgentLoom M2 产物\n"


class FileWorkflowModel(OfflineChatModel):
    """确定性走过 write_file → present_files → 最终回答。"""

    def _respond(self, messages):
        last = messages[-1]
        if isinstance(last, HumanMessage):
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "write_file",
                        "args": {"path": OUTPUT_PATH, "content": OUTPUT_CONTENT},
                        "id": "write-1",
                        "type": "tool_call",
                    }
                ],
                usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            )
        if isinstance(last, ToolMessage) and last.name == "write_file":
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "present_files",
                        "args": {"filepaths": [OUTPUT_PATH]},
                        "id": "present-1",
                        "type": "tool_call",
                    }
                ],
                usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            )
        return AIMessage(
            content="文件已经登记并可下载。",
            usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        )


def _wait(client: TestClient, run_id: str) -> dict:
    for _ in range(300):
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] in {"succeeded", "failed", "cancelled"}:
            return run
        time.sleep(0.01)
    raise AssertionError(f"Run 未结束：{run}")


def test_agent_creates_immutable_registered_artifact(tmp_path) -> None:
    app = create_app(tmp_path, config=AppConfig(), model=FileWorkflowModel())
    with TestClient(app) as client:
        thread_id = client.post("/api/threads", json={}).json()["thread_id"]
        submitted = client.post(
            f"/api/threads/{thread_id}/runs",
            json={"text": "生成并展示报告", "attachment_ids": [], "client_request_id": str(uuid4())},
        )
        run_id = submitted.json()["run_id"]
        assert _wait(client, run_id)["status"] == "succeeded"

        messages = client.get(f"/api/threads/{thread_id}/messages").json()["items"]
        presented = next(
            item for item in messages if item["role"] == "tool" and item["content"]["name"] == "present_files"
        )
        payload = json.loads(presented["content"]["text"])
        artifact_id = payload["artifacts"][0]["id"]

        metadata = client.get(f"/api/artifacts/{artifact_id}")
        content = client.get(f"/api/artifacts/{artifact_id}/content")
        assert metadata.status_code == 200
        assert metadata.json()["run_id"] == run_id
        assert metadata.json()["display_name"] == "report.txt"
        assert "relative_path" not in metadata.json()
        assert content.status_code == 200 and content.content == OUTPUT_CONTENT.encode()

        # 后续修改 outputs 原文件不会改变已经捕获的不可变快照。
        current = app.state.workspace.read_text(thread_id, OUTPUT_PATH)
        app.state.workspace.replace_text(
            thread_id,
            OUTPUT_PATH,
            old=OUTPUT_CONTENT,
            new="后来修改的内容\n",
            expected_sha256=current.sha256,
        )
        assert client.get(f"/api/artifacts/{artifact_id}/content").content == OUTPUT_CONTENT.encode()


def test_upload_and_integrity_failure_are_explicit(tmp_path) -> None:
    app = create_app(tmp_path, config=AppConfig())
    with TestClient(app) as client:
        thread_id = client.post("/api/threads", json={}).json()["thread_id"]
        upload = client.post(
            f"/api/threads/{thread_id}/uploads",
            files={"file": ("数据.csv", b"name,value\nA,1\n", "text/csv")},
        )
        assert upload.status_code == 201
        artifact_id = upload.json()["artifact_id"]
        assert upload.json()["virtual_path"].startswith("/mnt/user-data/uploads/")
        assert client.get(f"/api/artifacts/{artifact_id}/content").content == b"name,value\nA,1\n"

        relative = upload.json()["virtual_path"].removeprefix("/mnt/user-data/")
        physical = app.state.workspace.thread_root(thread_id).joinpath(*relative.split("/"))
        physical.write_bytes(b"corrupted")
        failed = client.get(f"/api/artifacts/{artifact_id}/content")
        assert failed.status_code == 409
        assert failed.json()["error"]["code"] == "ARTIFACT_INTEGRITY_FAILED"


def test_artifact_service_rejects_missing_and_cross_thread_access(tmp_path) -> None:
    async def scenario() -> None:
        app_path = tmp_path / "app.sqlite"
        migrate_database(app_path)
        sessions = create_sessionmaker(app_path)
        workspace = WorkspaceService(tmp_path / "threads")
        artifacts = ArtifactService(sessions, workspace)
        manager = RunManager(sessions, model_name="test")
        try:
            first = await manager.create_thread()
            second = await manager.create_thread()
            run = await manager.submit(first.id, text="artifact", client_request_id=str(uuid4()))
            assert await manager.try_start(run.id)
            workspace.write_text(first.id, OUTPUT_PATH, OUTPUT_CONTENT)
            records = await artifacts.register_outputs(first.id, run.id, [OUTPUT_PATH])

            with pytest.raises(ArtifactNotFound, match="不属于当前线程"):
                await artifacts.get(records[0].id, thread_id=second.id)
            with pytest.raises(WorkspaceError, match="文件不存在"):
                await artifacts.register_outputs(first.id, run.id, ["/mnt/user-data/outputs/missing.txt"])
        finally:
            await sessions.kw["bind"].dispose()

    asyncio.run(scenario())
