"""Small side-effect-free tools available to the current Lead Agent."""

from collections.abc import Mapping

from langchain_core.tools import BaseTool, StructuredTool, tool

from agentloom.memory.tools import MEMORY_TOOLS
from agentloom.tools.command import COMMAND_TOOLS
from agentloom.tools.files import FILE_TOOLS
from agentloom.tools.skills import SKILL_TOOLS
from agentloom.tools.task import TASK_TOOLS

DEFAULT_NOTES = {
    "AgentLoom": "AgentLoom 使用 create_agent 组装模型、工具和可恢复状态。",
}


@tool
def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


def make_lookup_note(notes: Mapping[str, str]) -> StructuredTool:
    """Create a read-only note lookup backed by injected local data."""

    def lookup_note(topic: str) -> str:
        return notes.get(topic, f"未找到主题“{topic}”的笔记")

    return StructuredTool.from_function(
        func=lookup_note,
        name="lookup_note",
        description="Read one fixed local note by its exact topic.",
    )


def get_builtin_tools(notes: Mapping[str, str] | None = None) -> list[BaseTool]:
    return [
        add,
        make_lookup_note(DEFAULT_NOTES if notes is None else notes),
        *FILE_TOOLS,
        *COMMAND_TOOLS,
        *SKILL_TOOLS,
        *TASK_TOOLS,
        *MEMORY_TOOLS,
    ]
