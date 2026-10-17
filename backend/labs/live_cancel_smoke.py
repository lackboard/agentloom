"""真实模型提出 Bash，批准后取消真实容器并验证账本收尾。"""

import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from agentloom.api import create_app
from agentloom.config import ConfigurationError, load_config


def wait_status(client: TestClient, run_id: str, expected: set[str], timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] in expected:
            return run
        time.sleep(0.05)
    raise TimeoutError(f"Run 未进入预期状态：{run}")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    docker = shutil.which("docker")
    if docker is None:
        print("LIVE CANCEL: NOT_RUN（找不到 docker 命令）")
        return 2
    try:
        config = load_config()
    except ConfigurationError as exc:
        print(f"LIVE CANCEL: NOT_RUN（{exc}）")
        return 2
    selected = config.models.default
    print(f"provider: {selected.provider}")
    print(f"model: {selected.model}")
    if selected.provider == "fake":
        print("LIVE CANCEL: NOT_RUN（provider 仍是 fake）")
        return 2

    try:
        with tempfile.TemporaryDirectory(prefix="agentloom-live-cancel-") as directory:
            app = create_app(Path(directory), config=config)
            with TestClient(app) as client:
                thread_id = client.post("/api/threads", json={}).json()["thread_id"]
                submitted = client.post(
                    f"/api/threads/{thread_id}/runs",
                    json={
                        "text": (
                            "请必须调用 bash，command 必须精确等于 sleep 30，evidence_paths 传空数组。"
                            "不要调用其他工具。"
                        ),
                        "attachment_ids": [],
                        "client_request_id": str(uuid4()),
                    },
                )
                submitted.raise_for_status()
                run_id = submitted.json()["run_id"]
                waiting = wait_status(client, run_id, {"waiting_input", "failed", "succeeded"}, 60)
                if waiting["status"] != "waiting_input":
                    raise RuntimeError(f"真实模型没有进入 Bash 审批：{waiting}")
                approval = client.get(f"/api/runs/{run_id}/approvals").json()["items"][0]
                approved = client.post(
                    f"/api/approvals/{approval['approval_id']}/resolve",
                    json={
                        "payload_hash": approval["payload_hash"],
                        "decision": "approve",
                        "reason": "真实取消 smoke",
                    },
                )
                approved.raise_for_status()

                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    ledger = client.get(f"/api/runs/{run_id}/tool-executions").json()["items"]
                    if ledger and ledger[0]["status"] == "running":
                        break
                    time.sleep(0.05)
                else:
                    raise TimeoutError(f"Bash 没有进入 running：{ledger}")

                cancelled = client.post(f"/api/runs/{run_id}/cancel")
                cancelled.raise_for_status()
                finished = wait_status(client, run_id, {"cancelled"}, 15)
                ledger = client.get(f"/api/runs/{run_id}/tool-executions").json()["items"]
                remaining = subprocess.run(
                    [docker, "ps", "--all", "--quiet", "--filter", f"label=agentloom.run_id={run_id}"],
                    capture_output=True,
                    text=True,
                    check=True,
                ).stdout.strip()
                if [(item["status"], item["error_code"], item["attempts"]) for item in ledger] != [
                    ("cancelled", "RUN_CANCELLED", 1)
                ]:
                    raise RuntimeError(f"取消后的工具账本不正确：{ledger}")
                if remaining:
                    raise RuntimeError(f"取消后仍有 Run 容器：{remaining}")

                print(f"approval: {waiting['status']} -> approved")
                print(f"run: {finished['status']}")
                print("ledger: cancelled / RUN_CANCELLED / attempts=1")
                print("container_remaining: false")
    except Exception as exc:
        print(f"LIVE CANCEL: FAIL（{type(exc).__name__}: {exc}）")
        return 1
    print("LIVE CANCEL: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
