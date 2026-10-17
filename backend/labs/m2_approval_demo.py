"""离线演示 M2.3～M2.4：整批暂停、批准恢复和工具账本。"""

import sys
import time
from collections.abc import Sequence
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
from pydantic import PrivateAttr

from agentloom.api import create_app
from agentloom.config import AppConfig
from agentloom.models.fake import OfflineChatModel


class ApprovalDemoModel(OfflineChatModel):
    """固定提出覆盖和普通写入，避免把随机模型输出当审批验收。"""

    _old_sha256: str = PrivateAttr(default="")

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
                            "expected_sha256": self._old_sha256,
                        },
                        "id": "replace-demo-1",
                        "type": "tool_call",
                    },
                    {
                        "name": "write_file",
                        "args": {
                            "path": "/mnt/user-data/outputs/side.txt",
                            "content": "审批后才创建",
                        },
                        "id": "write-demo-1",
                        "type": "tool_call",
                    },
                ],
            )
        if isinstance(messages[-1], ToolMessage):
            return AIMessage(content="审批后的工具批次已完成。")
        raise TypeError("演示模型只处理 HumanMessage 或 ToolMessage")


def wait_status(client: TestClient, run_id: str, expected: set[str]) -> dict:
    result = {}
    for _ in range(300):
        result = client.get(f"/api/runs/{run_id}").json()
        if result.get("status") in expected:
            return result
        time.sleep(0.01)
    raise RuntimeError(f"Run 未进入预期状态：{result}")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    with TemporaryDirectory(prefix=".m2-approval-", dir=Path.cwd()) as folder:
        model = ApprovalDemoModel()
        app = create_app(Path(folder), config=AppConfig(), model=model)
        with TestClient(app) as client:
            thread_id = client.post("/api/threads", json={}).json()["thread_id"]
            initial = app.state.workspace.write_text(
                thread_id,
                "/mnt/user-data/workspace/note.txt",
                "第一版",
            )
            model._old_sha256 = initial.sha256
            submitted = client.post(
                f"/api/threads/{thread_id}/runs",
                json={"text": "演示审批", "attachment_ids": [], "client_request_id": str(uuid4())},
            ).json()
            run_id = submitted["run_id"]
            waiting = wait_status(client, run_id, {"waiting_input"})
            approval = client.get(f"/api/runs/{run_id}/approvals").json()["items"][0]
            side_file = app.state.workspace.thread_root(thread_id) / "outputs" / "side.txt"
            print(f"waiting: status={waiting['status']} approval_id={approval['approval_id']}")
            print(
                "before_approval: "
                f"note={app.state.workspace.read_text(thread_id, '/mnt/user-data/workspace/note.txt').content} "
                f"side_exists={side_file.exists()}"
            )
            client.post(
                f"/api/approvals/{approval['approval_id']}/resolve",
                json={
                    "payload_hash": approval["payload_hash"],
                    "decision": "approve",
                    "reason": "离线演示批准",
                },
            ).raise_for_status()
            finished = wait_status(client, run_id, {"succeeded", "failed"})
            ledger = client.get(f"/api/runs/{run_id}/tool-executions").json()["items"]
            print(f"finished: status={finished['status']} same_run={finished['run_id'] == run_id}")
            print(
                "after_approval: "
                f"note={app.state.workspace.read_text(thread_id, '/mnt/user-data/workspace/note.txt').content} "
                f"side_exists={side_file.exists()}"
            )
            print("ledger: " + str([(item["tool_name"], item["status"], item["attempts"]) for item in ledger]))


if __name__ == "__main__":
    main()
