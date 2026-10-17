"""用本机真实模型验证 M4.1～M4.2 的一次隔离委派闭环。"""

import json
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from agentloom.api import create_app
from agentloom.config import ConfigurationError, load_config


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    config = load_config()
    selected = config.models.default
    print(f"provider: {selected.provider}")
    print(f"model: {selected.model}")
    if selected.provider == "fake":
        print("LIVE SUBAGENT: NOT_RUN（config.yaml 的 provider 仍是 fake）")
        return 2

    try:
        with tempfile.TemporaryDirectory(prefix="agentloom-m4-live-") as directory:
            data_dir = Path(directory)
            with TestClient(create_app(data_dir, config=config)) as client:
                thread_id = client.post("/api/threads", json={}).json()["thread_id"]
                prompt = (
                    "必须调用一次 task 工具：agent_type 使用 researcher；prompt 要求子 Agent 必须调用 add "
                    "计算 21 + 21 并在最终摘要中写出结果；expected_outputs 填写‘包含数字 42 的摘要’。"
                    "收到 task 的结构化结果后再简短汇总，不要由 Lead 自己调用 add。"
                )
                submitted = client.post(
                    f"/api/threads/{thread_id}/runs",
                    json={"text": prompt, "attachment_ids": [], "client_request_id": str(uuid4())},
                )
                if submitted.status_code != 202:
                    raise RuntimeError(f"提交失败：{submitted.status_code} {submitted.text}")
                run_id = submitted.json()["run_id"]
                deadline = time.monotonic() + max(60.0, selected.timeout_seconds * 6)
                while time.monotonic() < deadline:
                    run = client.get(f"/api/runs/{run_id}").json()
                    if run["status"] in {"succeeded", "failed", "cancelled"}:
                        break
                    time.sleep(0.1)
                else:
                    raise TimeoutError("真实子 Agent Run 未在期限内结束")
                if run["status"] != "succeeded":
                    raise RuntimeError(f"真实 Run 失败：{run['error']}")

                messages = client.get(f"/api/threads/{thread_id}/messages").json()["items"]
                tool_messages = [item for item in messages if item["role"] == "tool"]
                names = [item["content"].get("name") for item in tool_messages]
                if names != ["task"]:
                    raise RuntimeError(f"Lead 消息不应混入子 Agent 内部工具消息：{names}")
                task_payload = json.loads(tool_messages[0]["content"]["text"])
                result = task_payload.get("result", {})
                if result.get("status") != "succeeded" or "42" not in result.get("summary", ""):
                    raise RuntimeError(f"子任务未返回包含 42 的成功摘要：{result}")

                connection = sqlite3.connect(data_dir / "app.sqlite")
                row = connection.execute(
                    "SELECT status, agent_type, result_json FROM subagent_tasks WHERE run_id = ?",
                    (run_id,),
                ).fetchone()
                events = connection.execute(
                    "SELECT event_type FROM run_events WHERE run_id = ? AND event_type LIKE 'subagent.%' ORDER BY seq",
                    (run_id,),
                ).fetchall()
                connection.close()
                if row is None or row[0:2] != ("succeeded", "researcher"):
                    raise RuntimeError(f"子任务持久化异常：{row}")

                print(f"run: {run['status']} lead_tools={names}")
                print(f"subagent: status={row[0]} type={row[1]} summary={result['summary']!r}")
                print(f"events: {[event[0] for event in events]}")
                print(f"usage: {run['usage']}")
                print("LIVE SUBAGENT: PASS")
                return 0
    except ConfigurationError as exc:
        print(f"LIVE SUBAGENT: NOT_RUN（{exc}）")
        return 2
    except Exception as exc:
        print(f"LIVE SUBAGENT: FAIL（{type(exc).__name__}: {exc}）")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
