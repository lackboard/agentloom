"""Lead Agent 可见的非递归 task 工具。"""

import json
from typing import Annotated, Literal

from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command
from pydantic import Field

from agentloom.runtime.context import LoomContext
from agentloom.subagents.contracts import SubagentRequest
from agentloom.subagents.repository import SubagentLimitExceeded, SubagentTaskConflict


@tool
async def task(
    agent_type: Literal["researcher", "coder"],
    prompt: Annotated[str, Field(min_length=1, max_length=8000)],
    runtime: ToolRuntime[LoomContext],
    expected_outputs: Annotated[list[str], Field(max_length=10)] | None = None,
    input_files: Annotated[list[str], Field(max_length=20)] | None = None,
) -> Command:
    """把一个边界清楚的任务委派给隔离的 Researcher 或 Coder，并等待结构化结果。"""
    tool_call_id = runtime.tool_call_id or "missing-tool-call-id"
    if runtime.context.subagents is None:
        payload = {"ok": False, "error": {"code": "SUBAGENT_UNAVAILABLE", "message": "当前运行环境未启用子 Agent"}}
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=json.dumps(payload, ensure_ascii=False),
                        tool_call_id=tool_call_id,
                        name="task",
                        status="error",
                    )
                ]
            }
        )
    request = SubagentRequest(
        agent_type=agent_type,
        prompt=prompt,
        expected_outputs=expected_outputs or [],
        input_files=input_files or [],
    )
    try:
        result = await runtime.context.subagents.execute(
            request,
            parent_thread_id=runtime.context.thread_id,
            run_id=runtime.context.run_id,
            parent_tool_call_id=tool_call_id,
            budget=runtime.context.budget,
        )
    except (SubagentLimitExceeded, SubagentTaskConflict) as exc:
        payload = {
            "ok": False,
            "error": {"code": exc.code, "message": str(exc)},
        }
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=json.dumps(payload, ensure_ascii=False),
                        tool_call_id=tool_call_id,
                        name="task",
                        status="error",
                    )
                ]
            }
        )
    payload = {"ok": result.status == "succeeded", "result": result.model_dump(mode="json")}
    return Command(
        update={
            "messages": [
                ToolMessage(
                    content=json.dumps(payload, ensure_ascii=False),
                    tool_call_id=tool_call_id,
                    name="task",
                    status="success" if result.status == "succeeded" else "error",
                )
            ],
            "delegations": [result.state_summary()],
        }
    )


TASK_TOOLS = [task]
