"""M4 的非递归子 Agent 执行器。"""

import asyncio
import json
from dataclasses import dataclass

from langchain.agents import AgentState, create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware, ToolCallLimitMiddleware
from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import LLMResult
from langchain_core.tools import BaseTool

from agentloom.artifacts import ArtifactService
from agentloom.runtime.budget import SharedBudgetMiddleware
from agentloom.runtime.context import LoomContext
from agentloom.sandbox import WorkspaceService
from agentloom.subagents.contracts import SubagentRequest, SubagentResult
from agentloom.subagents.repository import SubagentTaskConflict, SubagentTaskRepository
from agentloom.subagents.tools import replace_task_file, request_parent_action

ROLE_TOOL_NAMES = {
    "researcher": frozenset({"add", "lookup_note", "list_dir", "read_file"}),
    "coder": frozenset({"add", "list_dir", "read_file", "write_file", "replace_task_file", "request_parent_action"}),
}

ROLE_PROMPTS = {
    "researcher": (
        "你是只读 Researcher。只处理委派说明和提供的输入快照；给出来源与简洁结论。"
        "你不能写文件、执行 Bash、请求审批或再次委派子任务。"
    ),
    "coder": (
        "你是 Coder。/mnt/user-data/workspace 是本 task 的私有目录，不是父工作区。"
        "你可以在这里创建或按 hash 修改文件；不能执行 Bash、请求审批或再次委派。"
        "若需要运行验证命令，请在最终答复中明确建议 Lead 执行的命令，不得声称测试已经通过。"
    ),
}


@dataclass
class _UsageCollector(AsyncCallbackHandler):
    model_attempts: int = 0
    reported_attempts: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    async def on_chat_model_start(self, serialized, messages, **kwargs) -> None:
        self.model_attempts += 1

    async def on_llm_end(self, response: LLMResult, **kwargs) -> None:
        found = False
        for generations in response.generations:
            for generation in generations:
                usage = getattr(generation.message, "usage_metadata", None)
                if usage:
                    self.input_tokens += int(usage.get("input_tokens", 0))
                    self.output_tokens += int(usage.get("output_tokens", 0))
                    found = True
        if found:
            self.reported_attempts += 1

    @property
    def complete(self) -> bool:
        return self.model_attempts == self.reported_attempts


def _message_text(message: AIMessage) -> str:
    if isinstance(message.content, str):
        return message.content
    parts = []
    for block in message.content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and isinstance(block.get("text"), str):
            parts.append(block["text"])
    return "\n".join(parts)


class SubagentExecutor:
    """在同一事件循环并发执行有界、可取消且不递归的 child graph。"""

    def __init__(
        self,
        *,
        model: BaseChatModel,
        tools: list[BaseTool],
        workspace: WorkspaceService,
        artifacts: ArtifactService,
        repository: SubagentTaskRepository,
        timeout_seconds: float = 120.0,
        max_model_attempts: int = 8,
        max_tool_executions: int = 12,
        max_tasks_per_run: int = 4,
        max_running: int = 2,
    ) -> None:
        self.model = model
        self.tools = list(tools)
        self.workspace = workspace
        self.artifacts = artifacts
        self.repository = repository
        self.timeout_seconds = timeout_seconds
        self.max_model_attempts = max_model_attempts
        self.max_tool_executions = max_tool_executions
        self.max_tasks_per_run = max_tasks_per_run
        self._capacity = asyncio.Semaphore(max_running)
        self._run_locks: dict[str, asyncio.Lock] = {}
        self._active: dict[str, set[asyncio.Task]] = {}
        self._closing = False

    def tools_for(self, agent_type: str) -> list[BaseTool]:
        """白名单从真实工具对象中过滤，并硬性排除递归委派与危险工具。"""
        candidates = [*self.tools, replace_task_file, request_parent_action]
        allowed = ROLE_TOOL_NAMES[agent_type]
        return [
            tool
            for tool in candidates
            if tool.name in allowed or (agent_type == "researcher" and tool.name.startswith("mcp__"))
        ]

    def _task_workspace(self, parent_thread_id: str) -> WorkspaceService:
        root = self.workspace.thread_root(parent_thread_id) / "tasks"
        return WorkspaceService(root, max_file_bytes=self.workspace.max_file_bytes)

    def _copy_inputs(
        self,
        request: SubagentRequest,
        *,
        parent_thread_id: str,
        task_id: str,
        task_workspace: WorkspaceService,
    ) -> list[dict[str, str]]:
        copied = []
        seen_targets: set[str] = set()
        for virtual_path in dict.fromkeys(request.input_files):
            source = self.workspace.inspect_file(parent_thread_id, virtual_path)
            # Windows 仍可能受传统 MAX_PATH 影响；目录名保留足够碰撞强度但不使用完整 hash。
            snapshot_key = source.sha256[:20]
            relative_path = f"uploads/{snapshot_key}/{source.name}"
            if relative_path not in seen_targets:
                target = task_workspace.store_snapshot(task_id, relative_path, source.content)
                seen_targets.add(relative_path)
            else:
                target = task_workspace.ensure_thread(task_id) / relative_path
            copied.append(
                {
                    "source_path": virtual_path,
                    "snapshot_path": f"/mnt/user-data/uploads/{snapshot_key}/{target.name}",
                    "sha256": source.sha256,
                }
            )
        return copied

    @staticmethod
    def _task_files(task_workspace: WorkspaceService, task_id: str) -> list[str]:
        workspace_root = task_workspace.ensure_thread(task_id) / "workspace"
        files = []
        for path in sorted(workspace_root.rglob("*")):
            if path.is_file() and not task_workspace._is_link_or_junction(path):
                files.append(f"/mnt/user-data/workspace/{path.relative_to(workspace_root).as_posix()}")
        return files[:100]

    @staticmethod
    def _parent_action(messages: list) -> dict | None:
        """从专用请求工具中提取结构化建议；自然语言不会被当作可执行命令。"""
        for message in reversed(messages):
            if not isinstance(message, ToolMessage) or message.name != "request_parent_action":
                continue
            try:
                payload = json.loads(message.content) if isinstance(message.content, str) else message.content
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(payload, dict) and isinstance(payload.get("requires_parent_action"), dict):
                return payload["requires_parent_action"]
        return None

    def _register_active(self, run_id: str) -> asyncio.Task:
        task = asyncio.current_task()
        if task is None:
            raise RuntimeError("子任务必须在 asyncio Task 中执行")
        self._active.setdefault(run_id, set()).add(task)
        return task

    def _forget_active(self, run_id: str, task: asyncio.Task) -> None:
        tasks = self._active.get(run_id)
        if tasks is None:
            return
        tasks.discard(task)
        if not tasks:
            self._active.pop(run_id, None)

    async def cancel_run(self, run_id: str) -> None:
        """取消该父 Run 的排队/执行中协程，并等待数据库终态完成。"""
        tasks = [task for task in self._active.get(run_id, set()) if not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await self.repository.cancel_open_for_run(run_id)

    async def close(self) -> None:
        """应用关闭时不遗留子任务协程。"""
        self._closing = True
        for run_id in list(self._active):
            await self.cancel_run(run_id)

    def active_count(self, run_id: str | None = None) -> int:
        if run_id is not None:
            return sum(not task.done() for task in self._active.get(run_id, set()))
        return sum(not task.done() for tasks in self._active.values() for task in tasks)

    async def execute(
        self,
        request: SubagentRequest,
        *,
        parent_thread_id: str,
        run_id: str,
        parent_tool_call_id: str,
        budget=None,
    ) -> SubagentResult:
        if self._closing:
            raise SubagentTaskConflict("子 Agent 执行器正在关闭")
        # 单进程范围内串行化“计数并创建”，避免同一 Run 的并发 task 越过总量上限。
        async with self._run_locks.setdefault(run_id, asyncio.Lock()):
            record = await self.repository.prepare(
                run_id,
                parent_tool_call_id,
                request.agent_type,
                request.prompt,
                timeout_seconds=self.timeout_seconds,
                expected_outputs=request.expected_outputs,
                max_tasks_per_run=self.max_tasks_per_run,
            )
        if record.status in {"succeeded", "failed", "cancelled", "interrupted"} and record.result is not None:
            return SubagentResult.model_validate(record.result)

        current_task = self._register_active(run_id)
        usage = _UsageCollector()
        task_workspace = self._task_workspace(parent_thread_id)
        try:
            # timeout 覆盖 semaphore 排队时间，而不只覆盖获得容量后的模型执行。
            async with asyncio.timeout(self.timeout_seconds):
                async with self._capacity:
                    if not await self.repository.start(record.id):
                        raise SubagentTaskConflict(f"子任务当前不能开始：{record.status}")
                    copied_inputs = await asyncio.to_thread(
                        self._copy_inputs,
                        request,
                        parent_thread_id=parent_thread_id,
                        task_id=record.id,
                        task_workspace=task_workspace,
                    )
                    child_tools = self.tools_for(request.agent_type)
                    child_agent = create_agent(
                        model=self.model,
                        tools=child_tools,
                        middleware=[
                            SharedBudgetMiddleware(),
                            ToolCallLimitMiddleware(run_limit=self.max_tool_executions, exit_behavior="continue"),
                            ModelCallLimitMiddleware(run_limit=self.max_model_attempts, exit_behavior="error"),
                        ],
                        state_schema=AgentState,
                        context_schema=LoomContext,
                        checkpointer=False,
                        system_prompt=ROLE_PROMPTS[request.agent_type],
                        name=f"agentloom-{request.agent_type}",
                    )
                    child_input = {
                        "messages": [
                            HumanMessage(
                                content=(
                                    f"任务：{request.prompt}\n"
                                    f"期望输出：{request.expected_outputs}\n"
                                    f"输入文件快照：{copied_inputs}"
                                )
                            )
                        ],
                    }
                    child_context = LoomContext(
                        thread_id=record.id,
                        run_id=run_id,
                        workspace=task_workspace,
                        artifacts=self.artifacts,
                        budget=budget,
                    )
                    state = await child_agent.ainvoke(
                        child_input,
                        config={"callbacks": [usage]},
                        context=child_context,
                    )
            final_message = next(message for message in reversed(state["messages"]) if isinstance(message, AIMessage))
            summary = _message_text(final_message).strip() or "子 Agent 未返回文本摘要"
            result = SubagentResult(
                task_id=record.id,
                agent_type=request.agent_type,
                status="succeeded",
                summary=summary,
                task_files=self._task_files(task_workspace, record.id),
                requires_parent_action=self._parent_action(state["messages"]),
                acceptance={
                    "expected_outputs": request.expected_outputs,
                    # 子 Agent 的自然语言声明不能提升为已验证测试证据。
                    "tests_passed": "unverified",
                },
            )
        except asyncio.CancelledError:
            cancelled = SubagentResult(
                task_id=record.id,
                agent_type=request.agent_type,
                status="cancelled",
                summary="父 Run 已取消，子任务已停止",
                acceptance={"expected_outputs": request.expected_outputs, "tests_passed": "unverified"},
                error={"code": "RUN_CANCELLED", "message": "父 Run 已取消"},
            )
            try:
                await self.repository.finish(
                    cancelled,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    usage_complete=usage.complete,
                )
            finally:
                self._forget_active(run_id, current_task)
            raise
        except Exception as exc:
            error_code = getattr(exc, "code", type(exc).__name__)
            result = SubagentResult(
                task_id=record.id,
                agent_type=request.agent_type,
                status="failed",
                summary=f"子任务失败：{type(exc).__name__}",
                acceptance={"expected_outputs": request.expected_outputs, "tests_passed": "unverified"},
                error={"code": error_code, "message": str(exc)[:2000]},
            )
        try:
            await self.repository.finish(
                result,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                usage_complete=usage.complete,
            )
            return result
        finally:
            self._forget_active(run_id, current_task)
