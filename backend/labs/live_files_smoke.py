"""用真实模型验证 M2.1～M2.2 的写文件、登记产物与下载闭环。"""

import json
import sys
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from agentloom.api import create_app
from agentloom.config import ConfigurationError, load_config

EXPECTED = "AgentLoom live artifact\n"
OUTPUT_PATH = "/mnt/user-data/outputs/live-note.txt"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    config = load_config()
    selected = config.models.default
    print(f"provider: {selected.provider}")
    print(f"model: {selected.model}")
    if selected.provider == "fake":
        print("LIVE FILES: NOT_RUN（config.yaml 的 provider 仍是 fake）")
        return 2

    try:
        with tempfile.TemporaryDirectory(prefix="agentloom-m2-live-") as directory:
            with TestClient(create_app(Path(directory), config=config)) as client:
                thread_id = client.post("/api/threads", json={}).json()["thread_id"]
                prompt = (
                    "请严格按顺序调用工具完成任务：先调用 write_file，在路径 "
                    f"{OUTPUT_PATH} 新建文件，content 必须精确等于字符串 "
                    '"AgentLoom live artifact\\n"；然后调用 present_files 登记这个文件；最后简短回复。'
                )
                submitted = client.post(
                    f"/api/threads/{thread_id}/runs",
                    json={"text": prompt, "attachment_ids": [], "client_request_id": str(uuid4())},
                )
                if submitted.status_code != 202:
                    raise RuntimeError(f"提交失败：{submitted.status_code} {submitted.text}")
                run_id = submitted.json()["run_id"]
                deadline = time.monotonic() + max(30.0, selected.timeout_seconds * 4)
                while time.monotonic() < deadline:
                    run = client.get(f"/api/runs/{run_id}").json()
                    if run["status"] in {"succeeded", "failed", "cancelled"}:
                        break
                    time.sleep(0.05)
                else:
                    raise TimeoutError("真实文件 Run 未在期限内结束")
                if run["status"] != "succeeded":
                    raise RuntimeError(f"真实文件 Run 失败：{run['error']}")

                messages = client.get(f"/api/threads/{thread_id}/messages").json()["items"]
                tool_messages = [item for item in messages if item["role"] == "tool"]
                names = [item["content"].get("name") for item in tool_messages]
                if names != ["write_file", "present_files"]:
                    raise RuntimeError(f"工具顺序不符合预期：{names}")
                presented = json.loads(tool_messages[-1]["content"]["text"])
                artifact_id = presented["artifacts"][0]["id"]
                content = client.get(f"/api/artifacts/{artifact_id}/content")
                if content.status_code != 200 or content.content != EXPECTED.encode():
                    raise RuntimeError("下载内容与模型被要求写入的内容不一致")

                print(f"run: {run['status']} tools={names}")
                print(f"usage: {run['usage']}")
                print(f"artifact: id={artifact_id} bytes={len(content.content)} verified=True")
                print("LIVE FILES: PASS")
                return 0
    except ConfigurationError as exc:
        print(f"LIVE FILES: NOT_RUN（{exc}）")
        return 2
    except Exception as exc:
        print(f"LIVE FILES: FAIL（{type(exc).__name__}: {exc}）")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
