"""大工具结果外置与失败安全的消息上下文压缩。"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
    ToolMessage,
    get_buffer_string,
)
from langchain_core.messages.utils import count_tokens_approximately
from langchain_core.tools import BaseTool
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.runtime import Runtime
from langgraph.types import Command

from agentloom.agents.state import LoomState
from agentloom.runtime.budget import RunBudgetExceeded
from agentloom.runtime.context import LoomContext
from agentloom.runtime.projection import project_graph_messages
from agentloom.sandbox import WorkspaceError


class ContextCapacityError(RuntimeError):
    """原上下文超过硬上限且摘要没有产生可用替代内容。"""


class ToolResultMiddleware(AgentMiddleware[LoomState, LoomContext]):
    """完整结果先落盘，再把有界预览和可分页读取的引用交给模型。"""

    state_schema = LoomState

    def __init__(self, preview_bytes: int) -> None:
        self.preview_bytes = preview_bytes

    @staticmethod
    def _content_text(message: ToolMessage) -> str:
        if isinstance(message.content, str):
            return message.content
        return json.dumps(message.content, ensure_ascii=False, sort_keys=True)

    def _externalize_message(self, request: ToolCallRequest, message: ToolMessage) -> ToolMessage:
        text = self._content_text(message)
        encoded = text.encode("utf-8")
        # 如果结果小于预览阈值，则直接返回原消息；否则尝试落盘并返回带预览的引用。
        if len(encoded) <= self.preview_bytes:
            return message
        context = request.runtime.context
        if context is None:
            return message
        try:
            stored = context.workspace.store_tool_result(
                context.thread_id,
                context.run_id,
                str(request.tool_call.get("id") or message.tool_call_id),
                text,
            )
        except WorkspaceError as exc:
            payload = {
                "ok": False,
                "error": {
                    "code": "TOOL_RESULT_EXTERNALIZE_FAILED",
                    "message": str(exc),
                },
            }
            return message.model_copy(update={"content": json.dumps(payload, ensure_ascii=False), "status": "error"})
        preview = encoded[: self.preview_bytes].decode("utf-8", errors="ignore")
        payload = {
            "ok": message.status != "error",
            "externalized": True,
            "preview": preview,
            "truncated": True,
            "full_result_path": stored.virtual_path,
            "sha256": stored.sha256,
            "size_bytes": stored.size_bytes,
            "read_hint": "调用 read_file(path, start_char, max_chars<=512) 分块读取完整结果",
        }
        return message.model_copy(update={"content": json.dumps(payload, ensure_ascii=False)})

    def _transform(self, request: ToolCallRequest, result: ToolMessage | Command[Any]) -> ToolMessage | Command[Any]:
        if isinstance(result, ToolMessage):
            return self._externalize_message(request, result)
        if not isinstance(result, Command) or not isinstance(result.update, dict):
            return result
        update = dict(result.update)
        update["messages"] = [
            self._externalize_message(request, message) if isinstance(message, ToolMessage) else message
            for message in update.get("messages", [])
        ]
        return replace(result, update=update)

    def wrap_tool_call(self, request, handler):
        return self._transform(request, handler(request))

    async def awrap_tool_call(self, request, handler):
        result = await handler(request)
        return await asyncio.to_thread(self._transform, request, result)


@dataclass(frozen=True)
class CompactionPlan:
    """一次不会拆开工具调用组的压缩边界。"""

    messages_to_summarize: tuple[AnyMessage, ...]
    preserved_messages: tuple[AnyMessage, ...]
    estimated_tokens: int


class ContextCompactionMiddleware(AgentMiddleware[LoomState, LoomContext]):
    """达到预算阈值时摘要旧消息，并保留当前任务与最近完整工具组。"""

    state_schema = LoomState

    def __init__(
        self,
        model: BaseChatModel,
        tools: Sequence[BaseTool],
        *,
        context_window: int,
        max_output_tokens: int,
        compaction_fraction: float,
        max_model_attempts: int,
        keep_tool_groups: int = 2,
    ) -> None:
        self.model = model
        self.tools = list(tools)
        self.context_window = context_window
        self.max_output_tokens = max_output_tokens
        self.trigger_tokens = int(context_window * compaction_fraction)
        self.max_model_attempts = max_model_attempts
        self.keep_tool_groups = keep_tool_groups

    @staticmethod
    def _ensure_message_ids(messages: list[AnyMessage], run_id: str) -> None:
        # 消息 ID 补全函数：遍历消息列表，给没有 ID 的消息生成一个确定性 ID。
        for index, message in enumerate(messages):
            if message.id is not None:
                continue
            content_hash = hashlib.sha256(str(message.content).encode("utf-8")).hexdigest()
            message.id = str(uuid5(NAMESPACE_URL, f"agentloom:{run_id}:{index}:{message.type}:{content_hash}"))

    def _estimate_tokens(
        self,
        messages: Sequence[AnyMessage],
        state: LoomState,
        *,
        summary_override: str | None = None,
    ) -> int:
        dynamic = {
            "summary": summary_override if summary_override is not None else state.get("summary_text"),
            "todos": state.get("todos", []),
            "artifact_ids": state.get("artifact_ids", []),
            "active_skill": state.get("active_skill"),
        }
        dynamic_message = SystemMessage(content=json.dumps(dynamic, ensure_ascii=False, sort_keys=True))
        return count_tokens_approximately([*messages, dynamic_message], tools=self.tools)

    @staticmethod
    def _units(messages: list[AnyMessage]) -> list[tuple[int, int, bool]]:
        """返回 [start,end) 单元；带连续结果的 AI 工具调用构成一个不可拆单元。"""
        units: list[tuple[int, int, bool]] = []
        index = 0
        while index < len(messages):
            message = messages[index]
            if isinstance(message, AIMessage) and message.tool_calls:
                # 收集“期望的”工具调用 ID
                expected = {str(call.get("id")) for call in message.tool_calls if call.get("id")}
                end = index + 1
                observed: set[str] = set()
                while end < len(messages) and isinstance(messages[end], ToolMessage):
                    observed.add(str(messages[end].tool_call_id))
                    end += 1
                units.append((index, end, bool(expected) and expected.issubset(observed)))
                index = end
                continue
            units.append((index, index + 1, False))
            index += 1
        return units

    def plan(self, state: LoomState, *, force: bool = False) -> CompactionPlan | None:
        messages = list(state.get("messages", []))
        run_id = str(state.get("current_run_id") or "unknown-run")
        self._ensure_message_ids(messages, run_id)
        estimated = self._estimate_tokens(messages, state)
        if not force and estimated + self.max_output_tokens < self.trigger_tokens:
            return None

        units = self._units(messages)
        complete_groups = [unit for unit in units if unit[2]]
        cutoff = 0
        # 算裁剪切点
        if len(complete_groups) > self.keep_tool_groups:
            cutoff = complete_groups[-self.keep_tool_groups][0]
        elif len(units) > 6:
            cutoff = units[-6][0]
        if cutoff <= 0:
            return None

        latest_human_id = next(
            (message.id for message in reversed(messages) if isinstance(message, HumanMessage)),
            None,
        )
        to_summarize: list[AnyMessage] = []
        rescued: list[AnyMessage] = []
        for message in messages[:cutoff]:
            if isinstance(message, SystemMessage) or message.id == latest_human_id:
                rescued.append(message)
            else:
                to_summarize.append(message)
        if not to_summarize:
            return None
        """
            保留最近两组完整工具消息。
            摘要更早的完整组。
            重复 ToolMessage 仍跟随原工具组。
            保留最新 HumanMessage，也就是当前任务。
        """
        return CompactionPlan(
            messages_to_summarize=tuple(to_summarize),
            preserved_messages=tuple([*rescued, *messages[cutoff:]]),
            estimated_tokens=estimated,
        )

    @staticmethod
    def _summary_prompt(plan: CompactionPlan, previous_summary: str | None) -> str:
        history = get_buffer_string(list(plan.messages_to_summarize), format="xml")
        return f"""你是 Agent 上下文压缩器。只输出一份可继续执行任务的中文摘要。
                    保留：用户目标、已完成工作、失败事实、仍待完成步骤、工具结果中的文件引用。
                    不要把工具输出预览误写成全文，不要编造未执行的操作。

                    上一版摘要：
                    {previous_summary or "（无）"}

                    本次旧消息：
                    {history}
                    """.strip()

    @staticmethod
    def _summary_text(response: Any) -> str | None:
        try:
            text = response.text if hasattr(response, "text") else response.content
        except Exception:
            return None
        return text.strip() if isinstance(text, str) and text.strip() else None

    def _hard_limit(self, plan: CompactionPlan | None) -> bool:
        return plan is not None and plan.estimated_tokens + self.max_output_tokens >= self.context_window

    def before_model(self, state: LoomState, runtime: Runtime[LoomContext]) -> dict[str, Any] | None:
        plan = self.plan(state)
        if plan is None:
            estimate = self._estimate_tokens(list(state.get("messages", [])), state)
            if estimate + self.max_output_tokens >= self.context_window:
                raise ContextCapacityError("上下文已超过模型容量，且没有可安全压缩的完整消息组")
            return None
        run_count = int(state.get("run_model_call_count", 0))
        thread_count = int(state.get("thread_model_call_count", 0))
        if run_count >= self.max_model_attempts:
            raise ContextCapacityError("上下文需要摘要，但本 Run 的模型调用预算已经耗尽")
        try:
            context = runtime.context
            if context is not None and context.budget is not None:
                context.budget.reserve_model_attempt()
            response = self.model.invoke(self._summary_prompt(plan, state.get("summary_text")))
            summary = self._summary_text(response)
        except RunBudgetExceeded:
            raise
        except Exception:
            summary = None
        if summary is None:
            if self._hard_limit(plan):
                raise ContextCapacityError("摘要生成失败，原消息已保留，但上下文无法容纳下一次模型请求")
            return {"run_model_call_count": run_count + 1, "thread_model_call_count": thread_count + 1}
        return self._update(state, plan, summary, run_count, thread_count)

    async def abefore_model(self, state: LoomState, runtime: Runtime[LoomContext]) -> dict[str, Any] | None:
        plan = self.plan(state)
        if plan is None:
            estimate = self._estimate_tokens(list(state.get("messages", [])), state)
            if estimate + self.max_output_tokens >= self.context_window:
                raise ContextCapacityError("上下文已超过模型容量，且没有可安全压缩的完整消息组")
            return None
        run_count = int(state.get("run_model_call_count", 0))
        thread_count = int(state.get("thread_model_call_count", 0))
        if run_count >= self.max_model_attempts:
            raise ContextCapacityError("上下文需要摘要，但本 Run 的模型调用预算已经耗尽")
        try:
            context = runtime.context
            if context is not None and context.budget is not None:
                context.budget.reserve_model_attempt()
            response = await self.model.ainvoke(self._summary_prompt(plan, state.get("summary_text")))
            summary = self._summary_text(response)
        except RunBudgetExceeded:
            raise
        except Exception:
            summary = None
        if summary is None:
            if self._hard_limit(plan):
                raise ContextCapacityError("摘要生成失败，原消息已保留，但上下文无法容纳下一次模型请求")
            return {"run_model_call_count": run_count + 1, "thread_model_call_count": thread_count + 1}

        projected = self._estimate_tokens(list(plan.preserved_messages), state, summary_override=summary)
        if projected + self.max_output_tokens >= self.context_window:
            raise ContextCapacityError("摘要仍无法把上下文压缩到模型容量以内，原消息未删除")
        context = runtime.context
        if context is not None and context.manager is not None:
            projections = project_graph_messages(context.run_id, list(plan.messages_to_summarize))
            await context.manager.archive_messages(context.run_id, projections)
        return self._update(state, plan, summary, run_count, thread_count)

    @staticmethod
    def _update(
        state: LoomState,
        plan: CompactionPlan,
        summary: str,
        run_count: int,
        thread_count: int,
    ) -> dict[str, Any]:
        return {
            "messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES), *plan.preserved_messages],
            "summary_text": summary,
            "compaction_count": int(state.get("compaction_count", 0)) + 1,
            # 摘要请求与下一次正式模型请求共享 ModelCallLimit 的同一计数器。
            "run_model_call_count": run_count + 1,
            "thread_model_call_count": thread_count + 1,
        }
