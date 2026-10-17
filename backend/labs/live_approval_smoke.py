"""显式真实模型 smoke：读取旧 hash、请求覆盖审批并恢复同一 Run。"""

import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from fastapi.testclient import TestClient

from agentloom.api import create_app
from agentloom.config import ConfigurationError, load_config


def wait_status(client: TestClient, run_id: str, expected: set[str]) -> dict:
    result = {}
    for _ in range(1200):
        result = client.get(f"/api/runs/{run_id}").json()
        if result.get("status") in expected:
            return result
        time.sleep(0.05)
    raise RuntimeError(f"Run 未进入预期状态：{result}")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        settings = load_config()
    except ConfigurationError as exc:
        print(f"LIVE APPROVAL: NOT_RUN（{exc}）")
        return 2
    selected = settings.models.default
    print(f"provider: {selected.provider}")
    print(f"model: {selected.model}")
    if selected.provider == "fake":
        print("LIVE APPROVAL: NOT_RUN（provider 仍是 fake）")
        return 2
    try:
        with TemporaryDirectory(prefix=".live-approval-", dir=Path.cwd()) as folder:
            app = create_app(Path(folder), config=settings)
            with TestClient(app) as client:
                thread_id = client.post("/api/threads", json={}).json()["thread_id"]
                app.state.workspace.write_text(
                    thread_id,
                    "/mnt/user-data/workspace/note.txt",
                    "第一版",
                )
                submitted = client.post(
                    f"/api/threads/{thread_id}/runs",
                    json={
                        "text": (
                            "请严格完成这个文件任务：先调用 read_file 读取 "
                            "/mnt/user-data/workspace/note.txt 并取得 sha256；然后调用 replace_file，"
                            "把唯一的“第一版”替换成“第二版”，expected_sha256 必须使用读取结果。"
                            "不要新建文件，不要跳过工具。"
                        ),
                        "attachment_ids": [],
                        "client_request_id": str(uuid4()),
                    },
                ).json()
                run_id = submitted["run_id"]
                waiting = wait_status(client, run_id, {"waiting_input", "failed", "succeeded"})
                if waiting["status"] != "waiting_input":
                    raise RuntimeError(f"模型没有进入审批等待：{waiting}")
                approval = client.get(f"/api/runs/{run_id}/approvals").json()["items"][0]
                before = app.state.workspace.read_text(thread_id, "/mnt/user-data/workspace/note.txt").content
                response = client.post(
                    f"/api/approvals/{approval['approval_id']}/resolve",
                    json={
                        "payload_hash": approval["payload_hash"],
                        "decision": "approve",
                        "reason": "真实模型 smoke 自动批准固定测试文件",
                    },
                )
                response.raise_for_status()
                finished = wait_status(client, run_id, {"succeeded", "failed"})
                after = app.state.workspace.read_text(thread_id, "/mnt/user-data/workspace/note.txt").content
                ledger = client.get(f"/api/runs/{run_id}/tool-executions").json()["items"]
                print(f"approval: before={before} waiting={waiting['status']}")
                print(f"finished: status={finished['status']} after={after}")
                print("ledger: " + str([(item["tool_name"], item["status"], item["attempts"]) for item in ledger]))
                if finished["status"] != "succeeded" or after != "第二版":
                    raise RuntimeError("真实模型审批恢复结果不符合预期")
    except Exception as exc:
        print(f"LIVE APPROVAL: FAIL（{type(exc).__name__}: {exc}）")
        return 1
    print("LIVE APPROVAL: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
