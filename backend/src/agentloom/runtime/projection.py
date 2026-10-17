"""把 LangGraph 消息转换成 app.sqlite/UI 使用的稳定投影。"""

from typing import Any
from uuid import NAMESPACE_URL, uuid5

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from agentloom.runtime.manager import MessageProjection


def _stable_message_id(run_id: str, index: int, message: BaseMessage) -> str:
    return str(message.id or uuid5(NAMESPACE_URL, f"agentloom:{run_id}:{index}:{message.type}"))


def _content(message: BaseMessage) -> dict:
    if isinstance(message.content, str):
        value: dict[str, Any] = {"text": message.content}
    else:
        # 真实 provider 常返回标准内容块；同时保留原始 blocks 和 LangChain
        # 归一化后的文本，避免 REST/UI/评测只能看到一个空回答。
        value = {
            "text": message.text,
            "blocks": message.model_dump(mode="json")["content"],
        }
    if isinstance(message, AIMessage) and message.tool_calls:
        value["tool_calls"] = message.tool_calls
    if isinstance(message, ToolMessage):
        value.update(tool_call_id=message.tool_call_id, name=message.name)
    return value


def project_graph_messages(run_id: str, messages: list[BaseMessage]) -> list[MessageProjection]:
    """投影 assistant/tool 消息；Human 输入已经在提交 Run 时持久化。"""
    projections: list[MessageProjection] = []
    for index, message in enumerate(messages):
        if isinstance(message, HumanMessage):
            continue
        message_id = _stable_message_id(run_id, index, message)
        if isinstance(message, AIMessage):
            role = "assistant"
        elif isinstance(message, ToolMessage):
            role = "tool"
        else:
            continue
        projections.append(MessageProjection(id=message_id, role=role, content=_content(message), events=()))
    return projections


def project_run_tail(
    run_id: str,
    input_message_id: str,
    messages: list[BaseMessage],
) -> list[MessageProjection]:
    """只投影当前稳定输入之后尚未由压缩钩子归档的新消息。"""
    input_index = next(
        (index for index, message in enumerate(messages) if str(message.id) == input_message_id),
        -1,
    )
    candidates = messages[input_index + 1 :] if input_index >= 0 else messages
    return project_graph_messages(run_id, candidates)
