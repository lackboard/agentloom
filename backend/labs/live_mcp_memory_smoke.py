"""用本机真实模型验证 M5.1 MCP 调用和 M5.2 偏好审批闭环。"""

import json
import sys
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from agentloom.api import create_app
from agentloom.config import ConfigurationError, load_config


def _submit(client: TestClient, thread_id: str, text: str) -> str:
    response = client.post(
        f"/api/threads/{thread_id}/runs",
        json={"text": text, "attachment_ids": [], "client_request_id": str(uuid4())},
    )
    if response.status_code != 202:
        raise RuntimeError(f"提交失败：{response.status_code} {response.text}")
    return response.json()["run_id"]


def _wait(client: TestClient, run_id: str, statuses: set[str], timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] in statuses:
            return run
        time.sleep(0.1)
    raise TimeoutError(f"Run 未进入 {statuses}")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    config = load_config()
    selected = config.models.default
    print(f"provider: {selected.provider}")
    print(f"model: {selected.model}")
    if selected.provider == "fake":
        print("LIVE M5: NOT_RUN（config.yaml 的 provider 仍是 fake）")
        return 2
    if not config.mcp.enabled:
        print("LIVE M5: NOT_RUN（config.yaml 未启用 MCP）")
        return 2

    timeout = max(60.0, selected.timeout_seconds * 4)
    try:
        with tempfile.TemporaryDirectory(prefix="agentloom-m5-live-") as directory:
            with TestClient(create_app(Path(directory), config=config)) as client:
                tools = client.get("/api/tools").json()
                diagnostic = tools["mcp_servers"][0]
                if diagnostic["status"] != "ready":
                    raise RuntimeError(f"MCP 未就绪：{diagnostic}")

                mcp_thread = client.post("/api/threads", json={}).json()["thread_id"]
                mcp_prompt = (
                    "必须调用 mcp__reference_library__search_references 工具，query 填 sqlite，limit 填 1。"
                    "收到工具结果后，简短回复并原样包含结果里的 local:// 来源。"
                )
                mcp_run_id = _submit(client, mcp_thread, mcp_prompt)
                mcp_run = _wait(client, mcp_run_id, {"succeeded", "failed", "cancelled"}, timeout)
                if mcp_run["status"] != "succeeded":
                    raise RuntimeError(f"MCP Run 失败：{mcp_run['error']}")
                mcp_executions = client.get(f"/api/runs/{mcp_run_id}/tool-executions").json()["items"]
                if not any(
                    item["tool_name"] == "mcp__reference_library__search_references" and item["status"] == "succeeded"
                    for item in mcp_executions
                ):
                    raise RuntimeError(f"真实模型没有成功调用指定 MCP 工具：{mcp_executions}")
                messages = client.get(f"/api/threads/{mcp_thread}/messages").json()["items"]
                serialized = json.dumps(messages, ensure_ascii=False)
                if "local://reference-library/sqlite-wal" not in serialized:
                    raise RuntimeError("MCP 工具结果或最终回复缺少受控来源")

                memory_thread = client.post("/api/threads", json={}).json()["thread_id"]
                memory_prompt = (
                    "这是我明确提出的长期偏好：回答时使用简体中文。必须调用 remember_preference，"
                    "memory_key 填 reply-language，content 填‘回答时使用简体中文’，expected_version 填 0。"
                )
                memory_run_id = _submit(client, memory_thread, memory_prompt)
                waiting = _wait(client, memory_run_id, {"waiting_input", "failed"}, timeout)
                if waiting["status"] != "waiting_input":
                    raise RuntimeError(f"偏好 Run 没有进入审批：{waiting['error']}")
                approval = client.get(f"/api/runs/{memory_run_id}/approvals").json()["items"][0]
                resolved = client.post(
                    f"/api/approvals/{approval['approval_id']}/resolve",
                    json={"payload_hash": approval["payload_hash"], "decision": "approve", "reason": None},
                )
                if resolved.status_code != 200:
                    raise RuntimeError(f"审批失败：{resolved.status_code} {resolved.text}")
                memory_run = _wait(client, memory_run_id, {"succeeded", "failed", "cancelled"}, timeout)
                memories = client.get("/api/memories").json()["items"]
                if memory_run["status"] != "succeeded" or len(memories) != 1:
                    raise RuntimeError(f"偏好没有成功保存：run={memory_run} memories={memories}")

                probe_thread = client.post("/api/threads", json={}).json()["thread_id"]
                probe_run_id = _submit(client, probe_thread, "请复述我已经确认的回答语言偏好。")
                probe_run = _wait(client, probe_run_id, {"succeeded", "failed", "cancelled"}, timeout)
                probe_messages = client.get(f"/api/threads/{probe_thread}/messages").json()["items"]
                if probe_run["status"] != "succeeded" or "简体中文" not in json.dumps(
                    probe_messages, ensure_ascii=False
                ):
                    raise RuntimeError("新线程的真实模型输出没有体现已确认偏好")

                print(
                    "mcp: "
                    f"run={mcp_run['status']} tool={mcp_executions[0]['tool_name']} "
                    f"status={mcp_executions[0]['status']}"
                )
                print(f"memory: approval=approved version={memories[0]['version']} new_thread={probe_run['status']}")
                print("LIVE M5: PASS")
                return 0
    except ConfigurationError as exc:
        print(f"LIVE M5: NOT_RUN（{exc}）")
        return 2
    except Exception as exc:
        print(f"LIVE M5: FAIL（{type(exc).__name__}: {exc}）")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
