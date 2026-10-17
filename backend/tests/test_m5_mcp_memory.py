import ctypes
import os
import time
from collections.abc import Sequence
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from pydantic import PrivateAttr

from agentloom.api import create_app
from agentloom.config import AppConfig, McpConfig
from agentloom.models.fake import OfflineChatModel


def _submit(client: TestClient, thread_id: str, text: str) -> str:
    response = client.post(
        f"/api/threads/{thread_id}/runs",
        json={"text": text, "attachment_ids": [], "client_request_id": str(uuid4())},
    )
    assert response.status_code == 202, response.text
    return response.json()["run_id"]


def _wait(client: TestClient, run_id: str, expected: set[str]) -> dict:
    result = {}
    for _ in range(400):
        result = client.get(f"/api/runs/{run_id}").json()
        if result.get("status") in expected:
            return result
        time.sleep(0.01)
    raise AssertionError(f"Run 未进入 {expected}：{result}")


class McpProbeModel(OfflineChatModel):
    """让真实 Agent 图调用 MCP，并在第二轮证明模型收到工具结果。"""

    _tool_content: str = PrivateAttr(default="")

    @property
    def tool_content(self) -> str:
        return self._tool_content

    def _respond(self, messages: Sequence[AnyMessage]) -> AIMessage:
        last = messages[-1]
        if isinstance(last, HumanMessage):
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "mcp__reference_library__search_references",
                        "args": {"query": "mcp", "limit": 1},
                        "id": "mcp-search-1",
                        "type": "tool_call",
                    }
                ],
                usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            )
        if isinstance(last, ToolMessage):
            self._tool_content = str(last.content)
            return AIMessage(
                content="已消费 MCP 查询结果。",
                usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            )
        raise TypeError(type(last).__name__)


class TimeoutThenBuiltinModel(OfflineChatModel):
    """按用户输入选择超时 MCP 或普通 add，验证失败隔离。"""

    def _respond(self, messages: Sequence[AnyMessage]) -> AIMessage:
        last = messages[-1]
        if isinstance(last, ToolMessage):
            return AIMessage(
                content=f"已观察工具结果：{last.content}",
                usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            )
        if not isinstance(last, HumanMessage):
            raise TypeError(type(last).__name__)
        if "慢 MCP" in str(last.content):
            call = {
                "name": "mcp__reference_library__slow_lookup",
                "args": {"query": "timeout"},
                "id": "mcp-slow-1",
                "type": "tool_call",
            }
        else:
            call = {"name": "add", "args": {"a": 2, "b": 3}, "id": "add-after-timeout", "type": "tool_call"}
        return AIMessage(
            content="",
            tool_calls=[call],
            usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        )


class PreferenceProbeModel(OfflineChatModel):
    """提出一次偏好保存，并记录每次真实模型请求收到的 system 内容。"""

    _system_texts: list[str] = PrivateAttr(default_factory=list)

    @property
    def system_texts(self) -> list[str]:
        return self._system_texts

    def _generate(self, messages: list[AnyMessage], stop=None, run_manager=None, **kwargs):
        self._system_texts.append(
            "\n".join(str(message.content) for message in messages if isinstance(message, SystemMessage))
        )
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    def _respond(self, messages: Sequence[AnyMessage]) -> AIMessage:
        last = messages[-1]
        if isinstance(last, ToolMessage):
            return AIMessage(
                content=f"偏好工具返回：{last.content}",
                usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            )
        if not isinstance(last, HumanMessage):
            raise TypeError(type(last).__name__)
        if "保存偏好" in str(last.content):
            # 故意省略默认 expected_version，验证审批点和执行点使用同一语义。
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "remember_preference",
                        "args": {"memory_key": "reply-language", "content": "回答使用中文"},
                        "id": "remember-1",
                        "type": "tool_call",
                    }
                ],
                usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            )
        return AIMessage(
            content="已检查偏好。",
            usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        )


def _process_is_running(pid: int) -> bool:
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        return True
    # Windows 没有可靠的 os.kill(pid, 0) 查询语义，直接读取进程退出码。
    process_query_limited_information = 0x1000
    still_active = 259
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        return False
    try:
        exit_code = ctypes.c_ulong()
        return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))) and exit_code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


def test_real_local_mcp_is_discovered_called_and_consumed(tmp_path) -> None:
    server = Path(__file__).parents[2] / "mcp_servers" / "reference_library" / "server.py"
    config = AppConfig(mcp=McpConfig(enabled=True, reference_library_script=server))
    model = McpProbeModel()

    with TestClient(create_app(tmp_path, config=config, model=model)) as client:
        tools = client.get("/api/tools").json()
        names = {item["name"] for item in tools["items"]}
        assert "add" in names
        assert "mcp__reference_library__search_references" in names
        assert tools["mcp_servers"] == [{"name": "reference_library", "status": "ready", "error": None}]

        thread_id = client.post("/api/threads", json={}).json()["thread_id"]
        run_id = _submit(client, thread_id, "查询 MCP 资料")
        assert _wait(client, run_id, {"succeeded"})["status"] == "succeeded"

        executions = client.get(f"/api/runs/{run_id}/tool-executions").json()["items"]
        assert [(item["tool_name"], item["status"], item["attempts"]) for item in executions] == [
            ("mcp__reference_library__search_references", "succeeded", 1)
        ]
        assert "mcp:reference_library" in model.tool_content
        assert "local://reference-library/mcp-protocol" in model.tool_content


def test_mcp_startup_failure_does_not_disable_builtin_tools(tmp_path) -> None:
    missing = tmp_path / "missing-mcp-server.py"
    config = AppConfig(mcp=McpConfig(enabled=True, reference_library_script=missing, startup_timeout_seconds=1))
    with TestClient(create_app(tmp_path, config=config, model=OfflineChatModel())) as client:
        tools = client.get("/api/tools").json()
        assert tools["mcp_servers"][0]["status"] == "unavailable"
        assert tools["mcp_servers"][0]["error"]["code"] == "MCP_UNAVAILABLE"
        assert all(not item["name"].startswith("mcp__") for item in tools["items"])

        thread_id = client.post("/api/threads", json={}).json()["thread_id"]
        run_id = _submit(client, thread_id, "请计算 2 + 3")
        assert _wait(client, run_id, {"succeeded"})["status"] == "succeeded"


def test_mcp_call_timeout_is_bounded_and_child_process_is_closed(tmp_path) -> None:
    pid_path = tmp_path / "mcp.pid"
    server_path = tmp_path / "slow_server.py"
    server_path.write_text(
        "\n".join(
            [
                "import asyncio",
                "import os",
                "from pathlib import Path",
                "from mcp.server.fastmcp import FastMCP",
                f"Path({str(pid_path)!r}).write_text(str(os.getpid()), encoding='ascii')",
                "server = FastMCP('slow-reference-library')",
                "@server.tool()",
                "async def slow_lookup(query: str) -> dict:",
                "    await asyncio.sleep(2)",
                "    return {'ok': True, 'query': query}",
                "if __name__ == '__main__':",
                "    server.run(transport='stdio')",
            ]
        ),
        encoding="utf-8",
    )
    config = AppConfig(
        mcp=McpConfig(
            enabled=True,
            reference_library_script=server_path,
            startup_timeout_seconds=3,
            call_timeout_seconds=0.05,
        )
    )

    with TestClient(create_app(tmp_path, config=config, model=TimeoutThenBuiltinModel())) as client:
        pid = int(pid_path.read_text(encoding="ascii"))
        assert _process_is_running(pid)
        thread_id = client.post("/api/threads", json={}).json()["thread_id"]
        started = time.monotonic()
        slow_run = _submit(client, thread_id, "调用慢 MCP")
        assert _wait(client, slow_run, {"succeeded"})["status"] == "succeeded"
        assert time.monotonic() - started < 1.5
        execution = client.get(f"/api/runs/{slow_run}/tool-executions").json()["items"][0]
        assert execution["status"] == "failed" and execution["error_code"] == "MCP_TIMEOUT"

        normal_thread = client.post("/api/threads", json={}).json()["thread_id"]
        normal_run = _submit(client, normal_thread, "验证普通工具")
        assert _wait(client, normal_run, {"succeeded"})["status"] == "succeeded"
        execution = client.get(f"/api/runs/{normal_run}/tool-executions").json()["items"][0]
        assert execution["tool_name"] == "add" and execution["status"] == "succeeded"

    for _ in range(100):
        if not _process_is_running(pid):
            break
        time.sleep(0.01)
    assert not _process_is_running(pid)


def test_confirmed_preference_is_injected_updated_versioned_and_deleted(tmp_path) -> None:
    model = PreferenceProbeModel()
    with TestClient(create_app(tmp_path, config=AppConfig(), model=model)) as client:
        thread_id = client.post("/api/threads", json={}).json()["thread_id"]
        run_id = _submit(client, thread_id, "保存偏好")
        waiting = _wait(client, run_id, {"waiting_input"})
        assert client.get("/api/memories").json()["items"] == []

        approval = client.get(f"/api/runs/{run_id}/approvals").json()["items"][0]
        assert approval["payload"]["actions"][0]["tool_name"] == "remember_preference"
        resolved = client.post(
            f"/api/approvals/{waiting['pending_approval_id']}/resolve",
            json={"payload_hash": approval["payload_hash"], "decision": "approve", "reason": None},
        )
        assert resolved.status_code == 200
        assert _wait(client, run_id, {"succeeded"})["status"] == "succeeded"

        created = client.get("/api/memories").json()["items"][0]
        assert created["content"] == "回答使用中文" and created["version"] == 1

        model.system_texts.clear()
        new_thread = client.post("/api/threads", json={}).json()["thread_id"]
        assert _wait(client, _submit(client, new_thread, "检查偏好一"), {"succeeded"})["status"] == "succeeded"
        assert any("回答使用中文" in text for text in model.system_texts)

        updated = client.patch(
            f"/api/memories/{created['id']}",
            json={"content": "回答使用简体中文，并保持简洁", "expected_version": 1},
        )
        assert updated.status_code == 200 and updated.json()["version"] == 2
        stale = client.patch(
            f"/api/memories/{created['id']}",
            json={"content": "过期客户端的修改", "expected_version": 1},
        )
        assert stale.status_code == 409
        assert stale.json()["error"]["code"] == "MEMORY_VERSION_CONFLICT"

        model.system_texts.clear()
        next_thread = client.post("/api/threads", json={}).json()["thread_id"]
        assert _wait(client, _submit(client, next_thread, "检查偏好二"), {"succeeded"})["status"] == "succeeded"
        assert any("回答使用简体中文，并保持简洁" in text for text in model.system_texts)

        deleted = client.request(
            "DELETE",
            f"/api/memories/{created['id']}",
            json={"expected_version": 2},
        )
        assert deleted.status_code == 200
        assert deleted.json()["status"] == "deleted" and deleted.json()["version"] == 3
        assert client.get("/api/memories").json()["items"] == []

        model.system_texts.clear()
        final_thread = client.post("/api/threads", json={}).json()["thread_id"]
        assert _wait(client, _submit(client, final_thread, "检查偏好三"), {"succeeded"})["status"] == "succeeded"
        assert all("回答使用简体中文，并保持简洁" not in text for text in model.system_texts)
