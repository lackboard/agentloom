"""用本机真实 provider 验证 M1 API worker、幂等、持久化事件与 usage。"""

import json
import sys
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from agentloom.api import create_app
from agentloom.config import ConfigurationError, load_config


def _events(response) -> list[dict]:
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    config = load_config()
    selected = config.models.default
    print(f"provider: {selected.provider}")
    print(f"model: {selected.model}")
    if selected.provider == "fake":
        print("LIVE API: NOT_RUN（config.yaml 的 provider 仍是 fake）")
        return 2

    try:
        with tempfile.TemporaryDirectory(prefix="agentloom-live-") as directory:
            with TestClient(create_app(Path(directory), config=config)) as client:
                thread_id = client.post("/api/threads", json={}).json()["thread_id"]
                request_id = str(uuid4())
                body = {
                    "text": "请使用 add 工具计算 7 + 8。",
                    "attachment_ids": [],
                    "client_request_id": request_id,
                }
                url = f"/api/threads/{thread_id}/runs"
                first = client.post(url, json=body)
                duplicate = client.post(url, json=body)
                conflict = client.post(url, json={**body, "text": "请计算 1 + 1"})
                if first.status_code != 202 or duplicate.status_code != 202 or conflict.status_code != 409:
                    raise RuntimeError(
                        f"入场结果异常：first={first.status_code}, duplicate={duplicate.status_code}, "
                        f"conflict={conflict.status_code}"
                    )
                run_id = first.json()["run_id"]
                if duplicate.json()["run_id"] != run_id:
                    raise RuntimeError("相同 client_request_id 没有返回同一 Run")

                deadline = time.monotonic() + max(30.0, selected.timeout_seconds * 3)
                while time.monotonic() < deadline:
                    run = client.get(f"/api/runs/{run_id}").json()
                    if run["status"] in {"succeeded", "failed", "cancelled"}:
                        break
                    time.sleep(0.05)
                else:
                    raise TimeoutError("真实 Run 未在期限内进入终态")
                if run["status"] != "succeeded":
                    raise RuntimeError(f"真实 Run 失败：{run['error']}")

                messages_before = client.get(f"/api/threads/{thread_id}/messages").json()["items"]
                events_before = _events(client.get(f"/api/runs/{run_id}/events"))
                completed_repeat = client.post(url, json=body)
                time.sleep(0.2)
                messages_after = client.get(f"/api/threads/{thread_id}/messages").json()["items"]
                events_after = _events(client.get(f"/api/runs/{run_id}/events"))
                if completed_repeat.json()["run_id"] != run_id:
                    raise RuntimeError("完成后重复提交没有返回原 Run")
                if messages_after != messages_before or events_after != events_before:
                    raise RuntimeError("完成后重复提交产生了新的消息或事件")
                if not any(item["role"] == "tool" and item["content"].get("text") == "15" for item in messages_after):
                    raise RuntimeError("持久化消息中没有 add 的真实结果 15")
                if not any(event["type"] == "tool.finished" for event in events_after):
                    raise RuntimeError("持久化事件中没有 tool.finished")

                print(f"run: {run['status']} same_run=True conflict=409")
                print(f"usage: {run['usage']}")
                print(f"messages: {len(messages_after)} events: {len(events_after)}")
                print("LIVE API: PASS")
                return 0
    except ConfigurationError as exc:
        print(f"LIVE API: NOT_RUN（{exc}）")
        return 2
    except Exception as exc:
        print(f"LIVE API: FAIL（{type(exc).__name__}: {exc}）")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
