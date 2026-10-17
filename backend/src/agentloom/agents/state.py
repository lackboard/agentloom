"""Serializable LangGraph state and its field-specific reducers."""

from typing import Annotated, NotRequired

from langchain.agents import AgentState
from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


def merge_todos(existing: list[dict[str, str]] | None, new: list[dict[str, str]] | None) -> list[dict[str, str]]:
    merged = {item["id"]: item for item in existing or []}
    for item in new or []:
        merged[item["id"]] = item
    return list(merged.values())


def merge_artifact_ids(existing: list[str] | None, new: list[str] | None) -> list[str]:
    return list(dict.fromkeys([*(existing or []), *(new or [])]))


def merge_delegations(existing: list[dict] | None, new: list[dict] | None) -> list[dict]:
    """按 task_id 合并有界子任务摘要；显式空列表用于新 Run 清空旧摘要。"""
    if new == []:
        return []
    merged = {str(item["task_id"]): item for item in existing or []}
    for item in new or []:
        merged[str(item["task_id"])] = item
    return list(merged.values())[-4:]


class LoomState(AgentState):
    """Execution state stored by LangGraph, separate from app.sqlite records."""

    messages: Annotated[list[AnyMessage], add_messages]
    current_run_id: NotRequired[str]
    todos: Annotated[list[dict[str, str]], merge_todos]
    artifact_ids: Annotated[list[str], merge_artifact_ids]
    delegations: Annotated[list[dict], merge_delegations]
    # Skill 正文与权限必须一起冻结在 checkpoint，恢复时不能重新读取磁盘版本。
    active_skill: NotRequired[dict | None]
    skill_activation_error: NotRequired[dict[str, str] | None]
    summary_text: NotRequired[str | None]
    compaction_count: NotRequired[int]
    stop_reason: NotRequired[str | None]
