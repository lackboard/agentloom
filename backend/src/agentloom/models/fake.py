"""Deterministic offline model used by tests and local development."""

import re
from collections.abc import Sequence

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

ADD_EXPRESSION = re.compile(r"(-?\d+)\s*\+\s*(-?\d+)")
NOTE_REQUEST = re.compile(r"(?:读取|查找)笔记[：:]\s*(.+)")


class OfflineChatModel(BaseChatModel):
    """Emit predictable tool calls while still using create_agent's tool node."""

    @property
    def _llm_type(self) -> str:
        return "agentloom-offline"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages: list[AnyMessage], stop=None, run_manager=None, **kwargs) -> ChatResult:
        last_user = max(index for index, message in enumerate(messages) if isinstance(message, HumanMessage))
        answer = self._respond(messages[last_user:])
        return ChatResult(generations=[ChatGeneration(message=answer)])

    def _respond(self, messages: Sequence[AnyMessage]) -> AIMessage:
        last = messages[-1]
        call_number = 1 + sum(isinstance(item, AIMessage) and bool(item.tool_calls) for item in messages)
        if isinstance(last, ToolMessage):
            return AIMessage(
                content=f"工具 {last.name} 返回：{last.content}。最终答案：{last.content}",
                usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            )
        if not isinstance(last, HumanMessage):
            raise TypeError("离线模型只接受 HumanMessage 或 ToolMessage")

        text = str(last.content)
        if match := ADD_EXPRESSION.search(text):
            name = "add"
            arguments = {"a": int(match.group(1)), "b": int(match.group(2))}
        else:
            note_match = NOTE_REQUEST.search(text)
            name = "lookup_note"
            arguments = {"topic": note_match.group(1).strip() if note_match else text.strip()}
        return AIMessage(
            content="",
            tool_calls=[{"name": name, "args": arguments, "id": f"call-{call_number}", "type": "tool_call"}],
            usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        )
