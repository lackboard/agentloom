"""Assemble AgentLoom's single formal model/tool execution chain."""

from collections.abc import Sequence

from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware, ToolCallLimitMiddleware
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import BaseTool

from agentloom.agents.context import ContextCompactionMiddleware, ToolResultMiddleware
from agentloom.agents.middleware import ApprovalMiddleware, ToolLedgerMiddleware
from agentloom.agents.state import LoomState
from agentloom.memory.middleware import PreferenceContextMiddleware
from agentloom.memory.tools import MEMORY_TOOLS
from agentloom.models.factory import create_chat_model
from agentloom.runtime.budget import SharedBudgetMiddleware
from agentloom.runtime.context import LoomContext
from agentloom.skills.policy import SkillActivationMiddleware, SkillContextMiddleware, SkillToolPolicyMiddleware
from agentloom.tools import get_builtin_tools
from agentloom.tools.skills import SKILL_TOOLS
from agentloom.tools.task import TASK_TOOLS


def _with_required_tools(tools: Sequence[BaseTool]) -> list[BaseTool]:
    """Skill 发现和 Lead 委派属于正式入口，自定义工具列表也不能移除它们。"""
    result = list(tools)
    names = {tool.name for tool in result}
    result.extend(tool for tool in [*SKILL_TOOLS, *TASK_TOOLS, *MEMORY_TOOLS] if tool.name not in names)
    return result


def create_loom_agent(
    *,
    model: BaseChatModel | None = None,
    tools: Sequence[BaseTool] | None = None,
    checkpointer=None,
    max_model_attempts: int = 24,
    max_tool_executions: int = 40,
    context_window: int = 32768,
    max_output_tokens: int = 4096,
    compaction_fraction: float = 0.70,
    tool_preview_bytes: int = 8192,
):
    """组装正式 Agent 图，并把单次 Run 的模型/工具预算放进图内执行。"""
    selected_model = model or create_chat_model()
    selected_tools = get_builtin_tools() if tools is None else _with_required_tools(tools)
    return create_agent(
        model=selected_model,
        tools=selected_tools,
        middleware=[
            SkillActivationMiddleware(),
            ContextCompactionMiddleware(
                selected_model,
                selected_tools,
                context_window=context_window,
                max_output_tokens=max_output_tokens,
                compaction_fraction=compaction_fraction,
                max_model_attempts=max_model_attempts,
            ),
            SkillContextMiddleware(),
            PreferenceContextMiddleware(),
            # 审批必须先于 ToolNode 运行；账本在真正执行点登记和重放结果。
            ApprovalMiddleware(),
            ToolLedgerMiddleware(),
            # 账本包在权限校验之外，因此越权尝试也会留下 failed 记录。
            SkillToolPolicyMiddleware(),
            # 位于账本和权限校验内部，只统计真正进入业务处理器的工具。
            SharedBudgetMiddleware(),
            ToolResultMiddleware(tool_preview_bytes),
            # 超额工具调用会收到 error ToolMessage，确保 tool_call_id 仍然成对。
            ToolCallLimitMiddleware(run_limit=max_tool_executions, exit_behavior="continue"),
            # 模型若收到工具错误后仍持续循环，则抛错，由 RunExecutor 记录 failed。
            ModelCallLimitMiddleware(run_limit=max_model_attempts, exit_behavior="error"),
        ],
        state_schema=LoomState,
        context_schema=LoomContext,
        checkpointer=checkpointer,
        name="agentloom",
    )
