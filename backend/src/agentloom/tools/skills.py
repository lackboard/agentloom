"""模型可调用的 Skill 发现与激活工具。"""

import asyncio
import json

from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from agentloom.runtime.context import LoomContext


def _message(tool_call_id: str, name: str, payload: dict, *, error: bool = False) -> ToolMessage:
    return ToolMessage(
        content=json.dumps(payload, ensure_ascii=False),
        name=name,
        tool_call_id=tool_call_id,
        status="error" if error else "success",
    )


@tool
async def list_skills(runtime: ToolRuntime[LoomContext]) -> dict:
    """列出可用 Skill 的名称、简介和允许工具；不会读取或返回 Skill 正文。"""
    context = runtime.context
    if context is None or context.skills is None:
        return {"ok": True, "skills": []}
    return {
        "ok": True,
        "skills": [item.model_dump(mode="json") for item in context.skills.list_skills()],
    }


@tool
async def load_skill(name: str, runtime: ToolRuntime[LoomContext]) -> Command:
    """按名称加载一个 Skill，并用其不可变快照替换当前活动 Skill。"""
    tool_call_id = runtime.tool_call_id or "missing-tool-call-id"
    context = runtime.context
    if context is None or context.skills is None:
        payload = {"ok": False, "error": {"code": "SKILLS_UNAVAILABLE", "message": "当前运行环境没有 SkillLoader"}}
        return Command(update={"messages": [_message(tool_call_id, "load_skill", payload, error=True)]})
    try:
        snapshot = await asyncio.to_thread(context.skills.load, name, activation="tool", run_id=context.run_id)
    except Exception as exc:
        payload = {
            "ok": False,
            "error": {"code": getattr(exc, "code", "SKILL_ERROR"), "message": str(exc)},
        }
        return Command(update={"messages": [_message(tool_call_id, "load_skill", payload, error=True)]})
    payload = {
        "ok": True,
        "skill": {
            "name": snapshot.name,
            "description": snapshot.description,
            "content_hash": snapshot.content_hash,
            "snapshot_ref": snapshot.snapshot_ref,
        },
    }
    return Command(
        update={
            "messages": [_message(tool_call_id, "load_skill", payload)],
            "active_skill": snapshot.to_state(),
            "skill_activation_error": None,
        }
    )


SKILL_TOOLS = [list_skills, load_skill]
