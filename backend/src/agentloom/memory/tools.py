"""由 Agent 提议、用户批准后才保存的偏好工具。"""

from typing import Annotated

from langchain.tools import ToolRuntime, tool
from pydantic import Field

from agentloom.runtime.context import LoomContext


@tool
async def remember_preference(
    memory_key: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")],
    content: Annotated[str, Field(min_length=1, max_length=2000)],
    runtime: ToolRuntime[LoomContext],
    expected_version: Annotated[int, Field(ge=0)] = 0,
) -> dict:
    """仅为用户明确表达的长期偏好发起保存；调用会先等待用户批准。"""
    context = runtime.context
    if context.memories is None or context.approvals is None:
        return {"ok": False, "error": {"code": "MEMORY_UNAVAILABLE", "message": "偏好服务未启用"}}
    arguments = {
        "memory_key": memory_key,
        "content": content,
        "expected_version": expected_version,
    }
    try:
        await context.approvals.authorize_preference(
            run_id=context.run_id,
            tool_call_id=runtime.tool_call_id or "missing-tool-call-id",
            arguments=arguments,
        )
        record = await context.memories.save_confirmed_preference(
            memory_key=memory_key,
            content=content,
            source_run_id=context.run_id,
            expected_version=expected_version,
        )
    except Exception as exc:
        return {
            "ok": False,
            "error": {"code": getattr(exc, "code", type(exc).__name__), "message": str(exc)},
        }
    return {
        "ok": True,
        "memory": {
            "id": record.id,
            "key": record.memory_key,
            "content": record.content,
            "version": record.version,
            "status": record.status,
        },
    }


MEMORY_TOOLS = [remember_preference]
