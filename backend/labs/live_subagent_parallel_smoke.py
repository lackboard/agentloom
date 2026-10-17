"""用本机真实模型验证 M4.3～M4.4 的双子任务委派与共享计量。"""

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
        print("LIVE PARALLEL SUBAGENT: NOT_RUN（config.yaml 的 provider 仍是 fake）")
        return 2

    try:
        with tempfile.TemporaryDirectory(prefix="agentloom-m4-parallel-live-") as directory:
            data_dir = Path(directory)
            with TestClient(create_app(data_dir, config=config)) as client:
                thread_id = client.post("/api/threads", json={}).json()["thread_id"]
                prompt = (
                    "请在同一条回复中同时调用两次 task 工具，两个 agent_type 都用 researcher。"
                    "第一个 prompt 要求必须调用 add 计算 10+11；第二个 prompt 要求必须调用 add 计算 20+22。"
                    "分别收到两个结构化结果后，汇总 21 和 42。不要由 Lead 自己调用 add。"
                )
                submitted = client.post(
                    f"/api/threads/{thread_id}/runs",
                    json={"text": prompt, "attachment_ids": [], "client_request_id": str(uuid4())},
                )
                if submitted.status_code != 202:
                    raise RuntimeError(f"提交失败：{submitted.status_code} {submitted.text}")
                run_id = submitted.json()["run_id"]
                deadline = time.monotonic() + max(90.0, selected.timeout_seconds * 10)
                while time.monotonic() < deadline:
                    run = client.get(f"/api/runs/{run_id}").json()
                    if run["status"] in {"succeeded", "failed", "cancelled"}:
                        break
                    time.sleep(0.1)
                else:
                    raise TimeoutError("真实并行子 Agent Run 未在期限内结束")
                if run["status"] != "succeeded":
                    raise RuntimeError(f"真实 Run 失败：{run['error']}")

                messages = client.get(f"/api/threads/{thread_id}/messages").json()["items"]
                task_messages = [
                    item for item in messages if item["role"] == "tool" and item["content"].get("name") == "task"
                ]
                if len(task_messages) != 2:
                    raise RuntimeError(f"Lead 应消费两个 task 结果，实际为 {len(task_messages)} 个")
                results = [json.loads(item["content"]["text"])["result"] for item in task_messages]
                if any(result.get("status") != "succeeded" for result in results):
                    raise RuntimeError(f"存在失败子任务：{results}")
                combined = "\n".join(result.get("summary", "") for result in results)
                if "21" not in combined or "42" not in combined:
                    raise RuntimeError(f"子任务摘要没有分别包含 21 和 42：{combined!r}")

                connection = sqlite3.connect(data_dir / "app.sqlite")
                rows = connection.execute(
                    "SELECT status, agent_type FROM subagent_tasks WHERE run_id = ? ORDER BY created_at",
                    (run_id,),
                ).fetchall()
                events = connection.execute(
                    "SELECT event_type FROM run_events WHERE run_id = ? AND event_type LIKE 'subagent.%' ORDER BY seq",
                    (run_id,),
                ).fetchall()
                connection.close()
                if rows != [("succeeded", "researcher"), ("succeeded", "researcher")]:
                    raise RuntimeError(f"子任务持久化异常：{rows}")

                print(f"run: {run['status']} task_results={len(results)}")
                print(f"summaries: {[result['summary'] for result in results]}")
                print(f"events: {[event[0] for event in events]}")
                print(f"shared_usage: {run['usage']}")
                print("LIVE PARALLEL SUBAGENT: PASS")
                return 0
    except ConfigurationError as exc:
        print(f"LIVE PARALLEL SUBAGENT: NOT_RUN（{exc}）")
        return 2
    except Exception as exc:
        print(f"LIVE PARALLEL SUBAGENT: FAIL（{type(exc).__name__}: {exc}）")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
