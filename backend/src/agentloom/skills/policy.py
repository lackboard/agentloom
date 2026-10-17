"""Skill 上下文注入、显式激活与工具权限双层校验。"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.runtime import Runtime
from pydantic import ValidationError

from agentloom.agents.state import LoomState
from agentloom.runtime.context import LoomContext
from agentloom.skills.schema import SkillSnapshot

DISCOVERY_TOOLS = frozenset({"list_skills", "load_skill"})
_SLASH_SKILL = re.compile(r"^/([a-z0-9][a-z0-9-]{0,63})(?:\s+|$)")


def active_skill(state: Mapping[str, Any] | Any) -> SkillSnapshot | None:
    """从不可信的 checkpoint 形状中严格恢复活动 Skill；无效数据按无权限处理。"""
    try:
        raw = state.get("active_skill") if isinstance(state, Mapping) else getattr(state, "active_skill", None)
        return None if raw is None else SkillSnapshot.model_validate(raw)
    except (ValidationError, TypeError, AttributeError):
        return None


def skill_allows_tool(state: Mapping[str, Any] | Any, tool_name: str) -> bool:
    """供审批和执行点共用：发现工具恒可用，其余取基础工具与 Skill 的交集。"""
    if tool_name in DISCOVERY_TOOLS:
        return True
    raw = state.get("active_skill") if isinstance(state, Mapping) else getattr(state, "active_skill", None)
    if raw is None:
        return True
    snapshot = active_skill(state)
    return snapshot is not None and tool_name in snapshot.allowed_tools


# 这是一个 LangGraph Agent 中间件，核心职责是：在每次模型调用之前，
# 检查用户是否输入了 /skill-name 斜杠命令，如果是且尚未激活，就加载对应的 Skill 快照并写入状态。
class SkillActivationMiddleware(AgentMiddleware[LoomState, LoomContext]):
    """在第一次模型调用前识别 `/skill-name` 并保存不可变快照。"""

    state_schema = LoomState

    # 这段代码是一个从消息历史里提取“斜杠 Skill 名”的工具函数：
    # 找到最近一条用户消息，如果它以 /skill 形式开头，就返回那个 Skill 名
    @staticmethod
    def _slash_name(state: LoomState) -> str | None:
        messages = state.get("messages", [])
        human = next((message for message in reversed(messages) if isinstance(message, HumanMessage)), None)
        if human is None or not isinstance(human.content, str):
            return None
        match = _SLASH_SKILL.match(human.content)
        return match.group(1) if match else None

    @classmethod
    def _load(cls, state: LoomState, runtime: Runtime[LoomContext]) -> dict[str, Any] | None:
        name = cls._slash_name(state)
        context = runtime.context
        if name is None or context is None or context.skills is None:
            return None
        run_id = str(state.get("current_run_id") or context.run_id)
        current = active_skill(state)
        if current is not None and current.activation == "slash" and current.run_id == run_id and current.name == name:
            return None
        try:
            snapshot = context.skills.load(name, activation="slash", run_id=run_id)
        except Exception as exc:
            code = getattr(exc, "code", "SKILL_ERROR")
            return {"active_skill": None, "skill_activation_error": {"code": code, "message": str(exc)}}
        return {"active_skill": snapshot.to_state(), "skill_activation_error": None}

    def before_model(self, state: LoomState, runtime: Runtime[LoomContext]) -> dict[str, Any] | None:
        return self._load(state, runtime)

    async def abefore_model(self, state: LoomState, runtime: Runtime[LoomContext]) -> dict[str, Any] | None:
        return await asyncio.to_thread(self._load, state, runtime)


class SkillContextMiddleware(AgentMiddleware[LoomState, LoomContext]):
    """每次模型请求动态组装 Skill 元数据；正文只来自已冻结快照。"""

    state_schema = LoomState

    @staticmethod
    def _section(request: ModelRequest[LoomContext]) -> str:
        context = request.runtime.context
        metadata = context.skills.list_skills() if context is not None and context.skills is not None else ()
        lines = ["<available_skills>"]
        lines.extend(f'- name="{item.name}" description="{item.description}"' for item in metadata)
        lines.extend(["</available_skills>", "需要某项技能时调用 load_skill；用户也可以用 /skill-name 显式激活。"])
        snapshot = active_skill(request.state)
        if snapshot is not None:
            lines.extend(
                [
                    f'<active_skill name="{snapshot.name}" sha256="{snapshot.content_hash}">',
                    snapshot.content,
                    "</active_skill>",
                ]
            )
        summary = request.state.get("summary_text")
        if isinstance(summary, str) and summary:
            lines.extend(["<conversation_summary>", summary, "</conversation_summary>"])
        todos = request.state.get("todos") or []
        if todos:
            lines.append(f"<current_todos>{json.dumps(todos, ensure_ascii=False)}</current_todos>")
        artifact_ids = request.state.get("artifact_ids") or []
        if artifact_ids:
            lines.append(f"<current_artifact_ids>{json.dumps(artifact_ids, ensure_ascii=False)}</current_artifact_ids>")
        error = request.state.get("skill_activation_error")
        if isinstance(error, dict):
            lines.append(f"<skill_activation_error>{json.dumps(error, ensure_ascii=False)}</skill_activation_error>")
        return "\n".join(lines)

    @classmethod
    def _prepare(cls, request: ModelRequest[LoomContext]) -> ModelRequest[LoomContext]:
        existing = request.system_message.content if request.system_message is not None else ""
        prefix = existing if isinstance(existing, str) else json.dumps(existing, ensure_ascii=False)
        # 拼接新 system message
        content = "\n\n".join(part for part in (prefix, cls._section(request)) if part)
        return request.override(system_message=SystemMessage(content=content))

    def wrap_model_call(self, request, handler: Callable[[ModelRequest], ModelResponse]):
        return handler(self._prepare(request))

    async def awrap_model_call(self, request, handler: Callable[[ModelRequest], Awaitable[ModelResponse]]):
        return await handler(self._prepare(request))


class SkillToolPolicyMiddleware(AgentMiddleware[LoomState, LoomContext]):
    """模型调用前隐藏越权 schema，工具执行点再做同一规则的强制校验。"""

    state_schema = LoomState

    @staticmethod
    def _filter(request: ModelRequest[LoomContext]) -> ModelRequest[LoomContext]:
        if request.state.get("active_skill") is None:
            return request
        tools = [tool for tool in request.tools if skill_allows_tool(request.state, getattr(tool, "name", ""))]
        return request.override(tools=tools)

    @staticmethod
    def _denied(request: ToolCallRequest) -> ToolMessage | None:
        call = request.tool_call
        name = str(call.get("name") or "unknown")
        if skill_allows_tool(request.state, name):
            return None
        snapshot = active_skill(request.state)
        skill_name = snapshot.name if snapshot is not None else "invalid-snapshot"
        return ToolMessage(
            content=json.dumps(
                {
                    "ok": False,
                    "error": {
                        "code": "SKILL_TOOL_DENIED",
                        "message": f"活动 Skill {skill_name} 不允许调用工具 {name}",
                    },
                },
                ensure_ascii=False,
            ),
            name=name,
            tool_call_id=str(call.get("id") or "missing-tool-call-id"),
            status="error",
        )

    def wrap_model_call(self, request, handler):
        return handler(self._filter(request))

    async def awrap_model_call(self, request, handler):
        return await handler(self._filter(request))

    def wrap_tool_call(self, request, handler):
        return self._denied(request) or handler(request)

    async def awrap_tool_call(self, request, handler):
        return self._denied(request) or await handler(request)
