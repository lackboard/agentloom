"""受信任本地 stdio MCP Server 的发现、调用和生命周期管理。"""

from __future__ import annotations

import asyncio
import re
import sys
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool
from langchain_mcp_adapters.tools import load_mcp_tools
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import get_default_environment, stdio_client

from agentloom.config import McpConfig

_SAFE_TOOL_NAME = re.compile(r"^[A-Za-z0-9_-]+$")
SERVER_NAME = "reference_library"


@dataclass(frozen=True)
class McpDiagnostic:
    """对外可见的 Server 状态；错误文本不包含命令环境或密钥。"""

    server: str
    status: str
    code: str | None = None
    message: str | None = None


class McpManager:
    """持有一个 stdio 子进程和 ClientSession，并把 MCP 工具包装为统一错误结构。"""

    def __init__(self, config: McpConfig, script_path: Path) -> None:
        self.config = config
        self.script_path = script_path
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None
        self._tools: list[BaseTool] = []
        self._diagnostic = McpDiagnostic(SERVER_NAME, "disabled" if not config.enabled else "starting")

    @property
    def tools(self) -> list[BaseTool]:
        return list(self._tools)

    @property
    def diagnostic(self) -> McpDiagnostic:
        return self._diagnostic

    async def start(self) -> list[BaseTool]:
        """有界启动并发现工具；失败只禁用该 Server，不阻断应用。"""
        if not self.config.enabled:
            return []
        stack = AsyncExitStack()
        try:
            async with asyncio.timeout(self.config.startup_timeout_seconds):
                parameters = StdioServerParameters(
                    command=sys.executable,
                    args=[str(self.script_path)],
                    env={
                        **get_default_environment(),
                        "PYTHONUTF8": "1",
                        "PYTHONIOENCODING": "utf-8",
                    },
                )
                read_stream, write_stream = await stack.enter_async_context(stdio_client(parameters))
                session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
                await session.initialize()
                discovered = await load_mcp_tools(session, server_name=SERVER_NAME)
            wrapped = self._wrap_discovered(discovered)
        except TimeoutError:
            await self._close_stack(stack)
            self._diagnostic = McpDiagnostic(
                SERVER_NAME,
                "unavailable",
                "MCP_STARTUP_TIMEOUT",
                f"MCP Server 初始化超过 {self.config.startup_timeout_seconds:g} 秒",
            )
            return []
        except Exception as exc:
            await self._close_stack(stack)
            self._diagnostic = McpDiagnostic(
                SERVER_NAME,
                "unavailable",
                "MCP_UNAVAILABLE",
                f"MCP Server 初始化失败：{type(exc).__name__}",
            )
            return []
        self._stack = stack
        self._session = session
        self._tools = wrapped
        self._diagnostic = McpDiagnostic(SERVER_NAME, "ready")
        return self.tools

    def _wrap_discovered(self, discovered: list[BaseTool]) -> list[BaseTool]:
        names: set[str] = set()
        wrapped = []
        for raw_tool in discovered:
            raw_name = raw_tool.name or ""
            if not _SAFE_TOOL_NAME.fullmatch(raw_name):
                continue
            public_name = f"mcp__{SERVER_NAME}__{raw_name}"
            if public_name in names:
                continue
            names.add(public_name)
            wrapped.append(self._wrap_tool(raw_tool, public_name, raw_name))
        return wrapped

    def _wrap_tool(self, raw_tool: BaseTool, public_name: str, raw_name: str) -> BaseTool:
        async def invoke_mcp(**arguments: Any) -> dict[str, Any]:
            try:
                async with asyncio.timeout(self.config.call_timeout_seconds):
                    result = await raw_tool.ainvoke(arguments)
            except TimeoutError:
                return {
                    "ok": False,
                    "source": f"mcp:{SERVER_NAME}",
                    "error": {
                        "code": "MCP_TIMEOUT",
                        "message": f"MCP 工具 {raw_name} 超过 {self.config.call_timeout_seconds:g} 秒未返回",
                        "retryable": True,
                    },
                }
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                return {
                    "ok": False,
                    "source": f"mcp:{SERVER_NAME}",
                    "error": {
                        "code": "MCP_UNAVAILABLE",
                        "message": f"MCP 工具 {raw_name} 调用失败：{type(exc).__name__}",
                        "retryable": True,
                    },
                }
            return {
                "ok": True,
                "source": f"mcp:{SERVER_NAME}",
                "tool": raw_name,
                "result": result,
            }

        tool = StructuredTool.from_function(
            coroutine=invoke_mcp,
            name=public_name,
            description=f"[来源: MCP/{SERVER_NAME}] {raw_tool.description}",
            args_schema=raw_tool.args_schema,
        )
        tool.metadata = {
            **(raw_tool.metadata or {}),
            "source": "mcp",
            "server": SERVER_NAME,
            "original_name": raw_name,
            "read_only": True,
        }
        return tool

    @staticmethod
    async def _close_stack(stack: AsyncExitStack) -> None:
        try:
            await asyncio.wait_for(stack.aclose(), timeout=5.0)
        except (TimeoutError, RuntimeError):
            # stdio_client 自己负责 terminate/kill；关闭错误不能阻断应用退出。
            pass

    async def close(self) -> None:
        """关闭 Session 和 stdio 子进程；重复调用安全。"""
        stack, self._stack = self._stack, None
        self._session = None
        self._tools = []
        if stack is not None:
            await self._close_stack(stack)
