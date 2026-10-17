"""用真实模型验证结构化工具失败会进入账本、事件并被模型消费。"""

import json
import sys
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from agentloom.api import create_app
from agentloom.config import ConfigurationError, load_config

MISSING_PATH = "/mnt/user-data/workspace/definitely-missing.txt"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        config = load_config()
    except ConfigurationError as exc:
        print(f"LIVE FAILURE: NOT_RUN（{exc}）")
        return 2
    selected = config.models.default
    print(f"provider: {selected.provider}")
    print(f"model: {selected.model}")
    if selected.provider == "fake":
        print("LIVE FAILURE: NOT_RUN（provider 仍是 fake）")
        return 2

    try:
        with tempfile.TemporaryDirectory(prefix="agentloom-live-failure-") as directory:
            with TestClient(create_app(Path(directory), config=config)) as client:
                thread_id = client.post("/api/threads", json={}).json()["thread_id"]
                submitted = client.post(
                    f"/api/threads/{thread_id}/runs",
                    json={
                        "text": (
                            f"请必须调用 read_file 读取 {MISSING_PATH}。"
                            "读取失败后不要再调用其他工具，直接说明工具报告的失败原因。"
                        ),
                        "attachment_ids": [],
                        "client_request_id": str(uuid4()),
                    },
                )
                submitted.raise_for_status()
                run_id = submitted.json()["run_id"]
                deadline = time.monotonic() + max(30.0, selected.timeout_seconds * 3)
                while time.monotonic() < deadline:
                    run = client.get(f"/api/runs/{run_id}").json()
                    if run["status"] in {"succeeded", "failed", "cancelled"}:
                        break
                    time.sleep(0.05)
                else:
                    raise TimeoutError("真实失败 Run 未在期限内结束")

                ledger = client.get(f"/api/runs/{run_id}/tool-executions").json()["items"]
                messages = client.get(f"/api/threads/{thread_id}/messages").json()["items"]
                events_response = client.get(f"/api/runs/{run_id}/events")
                events = [
                    json.loads(line[6:]) for line in events_response.text.splitlines() if line.startswith("data: ")
                ]
                tool_message = next(item for item in messages if item["role"] == "tool")
                payload = json.loads(tool_message["content"]["text"])
                final = next(item for item in reversed(messages) if item["role"] == "assistant")
                answer = final["content"].get("text") or "".join(
                    str(block.get("text") or "")
                    for block in final["content"].get("blocks", [])
                    if isinstance(block, dict)
                )

                if run["status"] != "succeeded":
                    raise RuntimeError(f"模型没有正常处理工具失败：{run['error']}")
                if len(ledger) != 1 or ledger[0]["status"] != "failed":
                    raise RuntimeError(f"工具失败没有正确写入账本：{ledger}")
                if ledger[0]["error_code"] != "FILE_NOT_FOUND" or payload.get("ok") is not False:
                    raise RuntimeError(f"具体工具错误码丢失：ledger={ledger}, payload={payload}")
                if not any(item["type"] == "tool.failed" for item in events):
                    raise RuntimeError("持久化事件中没有 tool.failed")
                if not answer or not any(
                    marker in answer for marker in ("不存在", "未找到", "FILE_NOT_FOUND", "missing")
                ):
                    raise RuntimeError(f"模型最终回答没有消费具体失败原因：{answer!r}")

                print(f"run: {run['status']} tool_status={ledger[0]['status']}")
                print(f"error_code: {ledger[0]['error_code']}")
                print(f"model_answer: {answer}")
    except Exception as exc:
        print(f"LIVE FAILURE: FAIL（{type(exc).__name__}: {exc}）")
        return 1
    print("LIVE FAILURE: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
