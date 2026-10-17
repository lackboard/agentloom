"""审批暂停与工具账本中间件。"""

import json
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.runtime import Runtime
from langgraph.types import Command, interrupt

from agentloom.agents.state import LoomState
from agentloom.runtime.approvals import ApprovalError
from agentloom.runtime.context import LoomContext
from agentloom.runtime.ledger import (
    ToolCallConflict,
    ToolResultUncertain,
    deserialize_tool_result,
    replay_class_for,
)
from agentloom.skills.policy import skill_allows_tool


def _error_message(tool_call: dict[str, Any], code: str, message: str) -> ToolMessage:
    return ToolMessage(
        content=json.dumps({"ok": False, "error": {"code": code, "message": message}}, ensure_ascii=False),
        name=str(tool_call.get("name") or "unknown"),
        tool_call_id=str(tool_call.get("id") or "missing-tool-call-id"),
        status="error",
    )


class ApprovalMiddleware(AgentMiddleware[LoomState, LoomContext]):
    """在任何工具开始前暂停包含文件覆盖、Bash 或偏好保存的整个工具批次。"""

    state_schema = LoomState

    def after_model(self, state: LoomState, runtime: Runtime[LoomContext]) -> dict[str, Any] | None:
        """同步教学调用不持有业务服务；危险工具仍会在执行点拒绝无审批调用。"""
        return None

    async def aafter_model(self, state: LoomState, runtime: Runtime[LoomContext]) -> dict[str, Any] | None:
        context = runtime.context
        if context is None or context.approvals is None or context.ledger is None:
            return None
        messages = state.get("messages", [])
        if not messages or not isinstance(messages[-1], AIMessage):
            return None
        message = messages[-1]
        tool_calls = list(message.tool_calls or [])
        if not any(
            call.get("name") in {"replace_file", "bash", "remember_preference"}
            and skill_allows_tool(state, str(call.get("name")))
            for call in tool_calls
        ):
            return None
        try:
            prepared = await context.approvals.prepare_tool_batch(
                context.thread_id,
                context.run_id,
                tool_calls,
            )
        except ApprovalError as exc:
            return {"messages": [_error_message(call, exc.code, str(exc)) for call in tool_calls]}

        approval = prepared.approval
        response = interrupt(
            {
                "version": 1,
                "kind": "tool_batch",
                "approval_id": approval.id,
                "payload_hash": approval.payload_hash,
                "payload": approval.payload,
            }
        )
        if not isinstance(response, dict):
            raise ApprovalError("恢复审批必须使用服务端生成的结构化答复")
        if response.get("approval_id") != approval.id or response.get("payload_hash") != approval.payload_hash:
            raise ApprovalError("恢复答复不属于当前审批")
        decision = response.get("decision")
        if decision not in {"approve", "reject"}:
            raise ApprovalError("审批答复只能是 approve 或 reject")
        await context.approvals.consume_response(approval.id, approval.payload_hash)
        if decision == "approve":
            return None

        reason = str(response.get("reason") or "用户拒绝了本批工具")
        for execution in prepared.executions:
            await context.ledger.deny(execution.id, reason=reason)
        # 为整批调用补齐失败 ToolMessage，保证下一次模型请求不存在悬空 tool call。
        return {"messages": [_error_message(call, "TOOL_BATCH_REJECTED", reason) for call in tool_calls]}


class ToolLedgerMiddleware(AgentMiddleware[LoomState, LoomContext]):
    """在执行点登记、去重并保存工具结果。"""

    state_schema = LoomState

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command[Any]],
    ) -> ToolMessage | Command[Any]:
        """同步教学调用没有 Run 账本，直接交给工具；正式 API 统一走异步路径。"""
        return handler(request)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        context = request.runtime.context
        if context is None or context.ledger is None:
            return await handler(request)
        call = request.tool_call
        tool_call_id = str(call.get("id") or "")
        tool_name = str(call.get("name") or "")
        arguments = call.get("args")
        if not tool_call_id or not tool_name or not isinstance(arguments, dict):
            return _error_message(call, "INVALID_TOOL_CALL", "工具调用缺少 ID、名称或结构化参数")
        try:
            record = await context.ledger.prepare(
                context.run_id,
                tool_call_id,
                tool_name,
                arguments,
                replay_class=replay_class_for(tool_name),
            )
        except ToolCallConflict as exc:
            return _error_message(call, exc.code, str(exc))

        if record.result is not None and record.status in {"succeeded", "failed"}:
            return deserialize_tool_result(record.result)
        if record.status == "denied":
            return _error_message(call, "TOOL_BATCH_REJECTED", "该工具批次已经被用户拒绝")
        if record.status in {"running", "uncertain"}:
            error = ToolResultUncertain("工具可能已经执行，当前不会自动重放")
            return _error_message(call, error.code, str(error))
        try:
            await context.ledger.begin(record.id)
            result = await handler(request)
            await context.ledger.finish(record.id, result)
            return result
        except Exception as exc:
            await context.ledger.fail_exception(record.id, exc)
            raise
