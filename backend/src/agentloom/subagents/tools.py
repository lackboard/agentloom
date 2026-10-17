"""只在 Coder 私有任务目录中启用的文件修改工具。"""

import asyncio
from typing import Annotated, Literal

from langchain.tools import ToolRuntime, tool
from pydantic import Field

from agentloom.runtime.context import LoomContext
from agentloom.sandbox import WorkspaceError


@tool
async def replace_task_file(
    path: str,
    old: str,
    new: str,
    expected_sha256: str,
    runtime: ToolRuntime[LoomContext],
) -> dict:
    """按 SHA-256 前置条件替换 Coder 私有目录中的唯一文本片段。"""
    try:
        result = await asyncio.to_thread(
            runtime.context.workspace.replace_text,
            runtime.context.thread_id,
            path,
            old=old,
            new=new,
            expected_sha256=expected_sha256,
        )
        return {
            "ok": True,
            "path": result.virtual_path,
            "sha256": result.sha256,
            "size_bytes": result.size_bytes,
        }
    except WorkspaceError as exc:
        return {"ok": False, "error": {"code": exc.code, "message": str(exc)}}


@tool
def request_parent_action(
    tool_name: Literal["bash"],
    command: Annotated[str, Field(min_length=1, max_length=4000)],
) -> dict:
    """只向 Lead 返回建议执行的命令；本工具不会执行命令或产生审批。"""
    return {
        "ok": True,
        "requires_parent_action": {
            "tool": tool_name,
            "command": command,
        },
    }
