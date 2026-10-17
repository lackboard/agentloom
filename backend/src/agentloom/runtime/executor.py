"""由应用生命周期持有的单进程 Run 执行器。"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.messages import HumanMessage
from langchain_core.outputs import LLMResult
from langgraph.types import Command

from agentloom.artifacts import ArtifactService
from agentloom.memory import MemoryService
from agentloom.runtime.approvals import ApprovalRecord, ApprovalService
from agentloom.runtime.budget import RunBudgetController
from agentloom.runtime.context import LoomContext
from agentloom.runtime.ledger import ToolLedgerService, tool_result_error_code
from agentloom.runtime.manager import EventDraft, MessageProjection, RunManager, RunNotFound, UsageTotals
from agentloom.runtime.projection import project_graph_messages, project_run_tail
from agentloom.runtime.streaming import PersistentMessageStream
from agentloom.sandbox import DockerCommandService, WorkspaceService
from agentloom.skills import SkillLoader
from agentloom.subagents import SubagentExecutor

TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}
logger = logging.getLogger(__name__)


class RunRecoveryBlocked(RuntimeError):
    """Run 仍有未解决的不确定工具结果。"""

    code = "RUN_RECOVERY_BLOCKED"


@dataclass
class _UsageCollector(AsyncCallbackHandler):
    """按模型尝试和真实工具开始事件收集最小计量。"""

    model_attempts: int = 0
    reported_attempts: int = 0
    tool_executions: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    tool_events: list[EventDraft] = field(default_factory=list)
    _active_tools: dict[str, dict] = field(default_factory=dict)
    budget: RunBudgetController | None = None
    manager: RunManager | None = None
    run_id: str | None = None
    root_span_id: str | None = None
    model_name: str | None = None
    _last_model_span_id: str | None = None

    def bind_trace(self, manager: RunManager, *, run_id: str, model_name: str) -> None:
        self.manager = manager
        self.run_id = run_id
        self.root_span_id = manager.root_span_id(run_id)
        self.model_name = model_name

    async def _trace_start(
        self,
        *,
        span_id: str,
        kind: str,
        name: str,
        attributes: dict,
        parent_span_id: str | None = None,
    ) -> None:
        if self.manager is None or self.run_id is None:
            return
        try:
            await self.manager.start_trace_span(
                self.run_id,
                span_id=span_id,
                parent_span_id=parent_span_id or self.root_span_id,
                kind=kind,
                name=name,
                attributes=attributes,
            )
        except Exception:
            # Trace 是诊断能力，不能把一次成功的模型/工具执行改写成业务失败。
            logger.warning("无法开始 Trace Span", exc_info=True)

    async def _trace_finish(
        self,
        *,
        span_id: str,
        status: str,
        attributes: dict | None = None,
        error_code: str | None = None,
    ) -> None:
        if self.manager is None or self.run_id is None:
            return
        try:
            await self.manager.finish_trace_span(
                self.run_id,
                span_id=span_id,
                status=status,
                attributes=attributes,
                error_code=error_code,
            )
        except Exception:
            logger.warning("无法结束 Trace Span", exc_info=True)

    async def on_chat_model_start(self, serialized, messages, **kwargs) -> None:
        self.model_attempts += 1
        span_id = str(kwargs.get("run_id"))
        self._last_model_span_id = span_id
        await self._trace_start(
            span_id=span_id,
            kind="model",
            name=self.model_name or "chat-model",
            attributes={"attempt": self.model_attempts},
        )

    async def on_llm_end(self, response: LLMResult, **kwargs) -> None:
        input_tokens = 0
        output_tokens = 0
        found = False
        for generations in response.generations:
            for generation in generations:
                usage = getattr(generation.message, "usage_metadata", None)
                if usage:
                    input_tokens += int(usage.get("input_tokens", 0))
                    output_tokens += int(usage.get("output_tokens", 0))
                    found = True
        if not found and response.llm_output:
            usage = response.llm_output.get("token_usage") or response.llm_output.get("usage")
            if usage:
                input_tokens = int(usage.get("prompt_tokens", usage.get("input_tokens", 0)))
                output_tokens = int(usage.get("completion_tokens", usage.get("output_tokens", 0)))
                found = True
        if found:
            self.reported_attempts += 1
            self.input_tokens += input_tokens
            self.output_tokens += output_tokens
        await self._trace_finish(
            span_id=str(kwargs.get("run_id")),
            status="succeeded",
            attributes={
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "usage_reported": found,
            },
        )

    async def on_llm_error(self, error, **kwargs) -> None:
        await self._trace_finish(
            span_id=str(kwargs.get("run_id")),
            status="failed",
            error_code=type(error).__name__,
        )

    async def on_tool_start(self, serialized, input_str, **kwargs) -> None:
        self.tool_executions += 1
        callback_id = str(kwargs.get("run_id"))
        call = {
            "tool_call_id": kwargs.get("tool_call_id"),
            "name": (serialized or {}).get("name"),
            "args": input_str,
            "status": "running",
        }
        self._active_tools[callback_id] = call
        self.tool_events.append(EventDraft("tool.started", call.copy()))
        await self._trace_start(
            span_id=callback_id,
            kind="tool",
            name=str(call.get("name") or "tool"),
            attributes={"tool_call_id": call.get("tool_call_id")},
            parent_span_id=self._last_model_span_id,
        )

    async def on_tool_end(self, output, **kwargs) -> None:
        callback_id = str(kwargs.get("run_id"))
        call = self._active_tools.pop(callback_id, {})
        error_code = None
        try:
            error_code = tool_result_error_code(output)
        except (TypeError, AttributeError):
            pass
        self.tool_events.append(
            EventDraft(
                "tool.failed" if error_code else "tool.finished",
                {
                    "tool_call_id": kwargs.get("tool_call_id") or call.get("tool_call_id"),
                    "name": call.get("name"),
                    "status": "failed" if error_code else "succeeded",
                    **({"error_code": error_code} if error_code else {}),
                },
            )
        )
        await self._trace_finish(
            span_id=callback_id,
            status="failed" if error_code else "succeeded",
            attributes={"tool_call_id": kwargs.get("tool_call_id") or call.get("tool_call_id")},
            error_code=error_code,
        )

    async def on_tool_error(self, error, **kwargs) -> None:
        callback_id = str(kwargs.get("run_id"))
        call = self._active_tools.pop(callback_id, {})
        self.tool_events.append(
            EventDraft(
                "tool.failed",
                {
                    "tool_call_id": kwargs.get("tool_call_id") or call.get("tool_call_id"),
                    "name": call.get("name"),
                    "status": "failed",
                    "error": f"{type(error).__name__}: {error}",
                },
            )
        )
        await self._trace_finish(
            span_id=callback_id,
            status="failed",
            attributes={"tool_call_id": kwargs.get("tool_call_id") or call.get("tool_call_id")},
            error_code=type(error).__name__,
        )

    def snapshot(self) -> UsageTotals:
        budget = self.budget.snapshot() if self.budget is not None else None
        model_attempts = self.model_attempts if budget is None else budget.model_attempts
        tool_executions = self.tool_executions if budget is None else budget.tool_executions
        return UsageTotals(
            model_attempts=model_attempts,
            tool_executions=tool_executions,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            complete=self.reported_attempts == model_attempts,
        )


class RunExecutor:
    """后台执行正式 Agent；HTTP/SSE 连接不拥有这些任务。"""

    def __init__(
        self,
        manager: RunManager,
        agent: Any,
        workspace: WorkspaceService,
        artifacts: ArtifactService,
        ledger: ToolLedgerService,
        approvals: ApprovalService,
        docker: DockerCommandService,
        skills: SkillLoader,
        memories: MemoryService,
        subagents: SubagentExecutor | None = None,
        *,
        max_running: int,
        max_model_attempts: int = 24,
        max_tool_executions: int = 40,
    ) -> None:
        self.manager = manager
        self.agent = agent
        self.workspace = workspace
        self.artifacts = artifacts
        self.ledger = ledger
        self.approvals = approvals
        self.docker = docker
        self.skills = skills
        self.memories = memories
        self.subagents = subagents
        self.max_model_attempts = max_model_attempts
        self.max_tool_executions = max_tool_executions
        # Semaphore 是异步信号量，用来限制同时进入某一段代码的任务数量。
        self._capacity = asyncio.Semaphore(max_running)
        self._tasks: dict[str, asyncio.Task] = {}
        self._usage: dict[str, _UsageCollector] = {}
        self._cleanup_tasks: set[asyncio.Task] = set()
        self._closing = False

    def start(self, run_id: str) -> None:
        if self._closing or run_id in self._tasks:
            return
        collector = _UsageCollector()
        task = asyncio.create_task(self._execute(run_id, collector), name=f"agentloom-run-{run_id}")
        self._tasks[run_id] = task
        self._usage[run_id] = collector
        # 无论 Task 正常结束、异常结束还是被取消，完成后都调用这个函数。
        task.add_done_callback(lambda completed: self._forget(run_id, completed))

    def resume(self, approval: ApprovalRecord) -> None:
        """用数据库中的固定答复恢复同一个 Run；重复调用不会创建第二个任务。"""
        if self._closing or approval.run_id in self._tasks or approval.response is None:
            return
        collector = _UsageCollector()
        command = {
            "approval_id": approval.id,
            "payload_hash": approval.payload_hash,
            **approval.response,
        }
        task = asyncio.create_task(
            self._execute(approval.run_id, collector, resume=command),
            name=f"agentloom-resume-{approval.run_id}",
        )
        self._tasks[approval.run_id] = task
        self._usage[approval.run_id] = collector
        task.add_done_callback(lambda completed: self._forget(approval.run_id, completed))

    async def recover(self, run_id: str) -> str:
        """在 uncertain 均已处理后，从原 checkpoint 继续同一个 Run。"""
        run = await self.manager.get_run(run_id)
        if run is None:
            raise RunNotFound(run_id)
        if run.status != "interrupted":
            return run.status
        if await self.ledger.has_uncertain(run_id):
            raise RunRecoveryBlocked("仍有 uncertain 工具结果；请先 verify 或 skip")
        if self._closing or run_id in self._tasks:
            return run.status
        collector = _UsageCollector()
        task = asyncio.create_task(self._execute(run_id, collector, recover=True), name=f"agentloom-recover-{run_id}")
        self._tasks[run_id] = task
        self._usage[run_id] = collector
        task.add_done_callback(lambda completed: self._forget(run_id, completed))
        return run.status

    def _forget(self, run_id: str, completed: asyncio.Task) -> None:
        # 主动读取异常，避免“Task exception was never retrieved”；BaseException
        # 可用于测试模拟进程骤停，此处只清理内存，不篡改数据库残留状态。
        if not completed.cancelled():
            completed.exception()
        if self._tasks.get(run_id) is completed:
            self._tasks.pop(run_id, None)
            self._usage.pop(run_id, None)

    async def _sync_actual_tool_attempts(
        self,
        run_id: str,
        collector: _UsageCollector,
        before: dict[str, int],
    ) -> None:
        """以账本 attempts 校正 callback；账本重放不是新的真实工具执行。"""
        after = await self.ledger.attempt_snapshot(run_id)
        collector.tool_executions = sum(after.values())
        started_ids = {
            tool_call_id for tool_call_id, attempts in after.items() if attempts > before.get(tool_call_id, 0)
        }
        collector.tool_events = [
            event for event in collector.tool_events if event.data.get("tool_call_id") in started_ids
        ]

    async def _execute(
        self,
        run_id: str,
        collector: _UsageCollector,
        *,
        resume: dict | None = None,
        recover: bool = False,
    ) -> None:
        attempt_snapshot: dict[str, int] = {}
        try:
            async with self._capacity:
                run_before = await self.manager.get_run(run_id)
                if run_before is None:
                    raise RunNotFound(run_id)
                if resume is not None or recover:
                    collector.model_attempts = run_before.model_attempts
                    collector.reported_attempts = run_before.model_attempts if run_before.usage_complete else 0
                    collector.tool_executions = run_before.tool_executions_count
                    collector.input_tokens = run_before.input_tokens
                    collector.output_tokens = run_before.output_tokens
                    acquired = (
                        await self.manager.try_recover(run_id) if recover else await self.manager.try_resume(run_id)
                    )
                else:
                    acquired = await self.manager.try_start(run_id)
                if not acquired:
                    run = await self.manager.get_run(run_id)
                    if run is not None and run.status == "cancelling":
                        await self._finalize_cancel(run_id, collector.snapshot())
                    return
                run = await self.manager.get_run(run_id)
                if run is None:
                    raise RunNotFound(run_id)
                collector.bind_trace(self.manager, run_id=run.id, model_name=run.model_name)
                await self.manager.start_root_trace(run.id)
                collector.budget = RunBudgetController(
                    max_model_attempts=self.max_model_attempts,
                    max_tool_executions=self.max_tool_executions,
                    initial_model_attempts=collector.model_attempts,
                    initial_tool_executions=collector.tool_executions,
                )
                run_input = json.loads(run.input_json)
                text = run_input["text"]
                attachments = run_input.get("attachments") or []
                if attachments:
                    text = (
                        f"{text}\n\n<user_attachments>\n"
                        f"{json.dumps(attachments, ensure_ascii=False)}\n"
                        "</user_attachments>\n"
                        "附件是服务端确认属于当前线程的只读快照；请按 virtual_path 使用文件工具读取。"
                    )
                attempt_snapshot = await self.ledger.attempt_snapshot(run.id)
                graph_input: dict | Command | None
                if recover:
                    graph_input = None
                elif resume is None:
                    graph_input = {
                        "messages": [HumanMessage(id=run.input_message_id, content=text)],
                        "current_run_id": run.id,
                        # 新 Run 不继承上一 Run 的 Skill；恢复/审批则沿用 checkpoint 快照。
                        "active_skill": None,
                        "skill_activation_error": None,
                        # 普通新 Run 不继承上一轮委派摘要；审批恢复继续使用 checkpoint。
                        "delegations": [],
                        "artifact_ids": list(run_input.get("attachment_ids") or []),
                    }
                else:
                    graph_input = Command(resume=resume)
                stream = self.agent.astream(
                    graph_input,
                    config={
                        "configurable": {"thread_id": run.thread_id},
                        "callbacks": [collector],
                    },
                    context=LoomContext(
                        thread_id=run.thread_id,
                        run_id=run.id,
                        workspace=self.workspace,
                        artifacts=self.artifacts,
                        ledger=self.ledger,
                        approvals=self.approvals,
                        docker=self.docker,
                        skills=self.skills,
                        manager=self.manager,
                        subagents=self.subagents,
                        budget=collector.budget,
                        memories=self.memories,
                    ),
                    stream_mode=["messages", "values"],
                )
                result = None
                message_stream = PersistentMessageStream(self.manager, run.id)
                try:
                    async for mode, payload in stream:
                        if mode == "messages":
                            message, _metadata = payload
                            await message_stream.add(message)
                        elif mode == "values":
                            result = payload
                finally:
                    try:
                        await message_stream.close()
                    finally:
                        await stream.aclose()
                if result is None:
                    raise RuntimeError("Agent 流结束但没有最终 State")
                interrupts = result.get("__interrupt__", [])
                if interrupts:
                    await self._sync_actual_tool_attempts(run.id, collector, attempt_snapshot)
                    payload = interrupts[0].value
                    if not isinstance(payload, dict) or not isinstance(payload.get("approval_id"), str):
                        raise RuntimeError("Agent 返回了无法识别的 interrupt")
                    snapshot = await self.agent.aget_state({"configurable": {"thread_id": run.thread_id}})
                    checkpoint_id = snapshot.config.get("configurable", {}).get("checkpoint_id")
                    if not isinstance(checkpoint_id, str) or not checkpoint_id:
                        raise RuntimeError("审批 interrupt 没有持久化 checkpoint")
                    waiting = await self.manager.wait_for_approval(
                        run.id,
                        payload["approval_id"],
                        checkpoint_id,
                        usage=collector.snapshot(),
                    )
                    if not waiting:
                        raise RuntimeError("Run 无法进入 waiting_input")
                    return
                # 将用户输入之后 Aimessage 和 Toolmessage 投影到 数据库中的 message 和 event 表
                await self._sync_actual_tool_attempts(run.id, collector, attempt_snapshot)
                messages = project_run_tail(run.id, run.input_message_id, result["messages"])
                completed = await self.manager.complete_success(
                    run.id,
                    messages=messages,
                    usage=collector.snapshot(),
                    events=collector.tool_events,
                )
                if not completed:
                    latest = await self.manager.get_run(run.id)
                    if latest is not None and latest.status == "cancelling":
                        await self._finalize_cancel(run.id, collector.snapshot())
        except asyncio.CancelledError:
            await self._sync_actual_tool_attempts(run_id, collector, attempt_snapshot)
            await self._finalize_cancel(run_id, collector.snapshot())
        except Exception as exc:
            await self._sync_actual_tool_attempts(run_id, collector, attempt_snapshot)
            failed = await self.manager.complete_failure(
                run_id,
                error=exc,
                usage=collector.snapshot(),
                events=collector.tool_events,
            )
            if not failed:
                latest = await self.manager.get_run(run_id)
                if latest is not None and latest.status == "cancelling":
                    await self._finalize_cancel(run_id, collector.snapshot())

    @staticmethod
    def _stored_usage(run) -> UsageTotals:
        return UsageTotals(
            model_attempts=run.model_attempts,
            tool_executions=run.tool_executions_count,
            input_tokens=run.input_tokens,
            output_tokens=run.output_tokens,
            complete=bool(run.usage_complete),
        )

    async def _finalize_cancel(self, run_id: str, usage: UsageTotals) -> None:
        """停止外部资源，并把所有尚未响应的 tool call 以失败结果配对。"""
        if self.subagents is not None:
            await self.subagents.cancel_run(run_id)
        await self.docker.cancel_run(run_id)
        await self.approvals.expire_pending_for_run(run_id)
        tool_messages = await self.ledger.cancel_open_for_run(run_id)
        run = await self.manager.get_run(run_id)
        projections: list[MessageProjection] = []
        if run is not None and tool_messages:
            await self.agent.aupdate_state(
                {"configurable": {"thread_id": run.thread_id}},
                {"messages": tool_messages},
            )
            projections.extend(project_graph_messages(run_id, tool_messages))
        await self.manager.finish_cancel(run_id, usage=usage, messages=projections)

    async def cancel(self, run_id: str) -> str:
        status = await self.manager.request_cancel(run_id)
        if status == "cancelling":
            task = self._tasks.get(run_id)
            collector = self._usage.get(run_id)
            if task is None or task.done():
                run = await self.manager.get_run(run_id)
                usage = (
                    collector.snapshot()
                    if collector is not None
                    else (UsageTotals() if run is None else self._stored_usage(run))
                )
                # 极小竞态：父 Task 已结束但 cancelling 尚未收尾。后台补偿并纳入 lifespan 管理。
                cleanup = asyncio.create_task(
                    self._finalize_cancel(run_id, usage),
                    name=f"agentloom-cancel-cleanup-{run_id}",
                )
                self._cleanup_tasks.add(cleanup)
                cleanup.add_done_callback(self._cleanup_tasks.discard)
            else:
                # 父图取消会沿 LangGraph 工具任务传播；_execute 负责最终资源与状态收尾。
                task.cancel()
            await asyncio.sleep(0)
            latest = await self.manager.get_run(run_id)
            return latest.status if latest is not None else status
        return status

    async def close(self) -> None:
        """优雅关闭时先持久化取消请求，再等待任务完成收尾。"""
        self._closing = True
        # 给已经越过最后一个外部副作用的任务一个很短的收尾窗口。这样异常退出
        # 能保留 running/uncertain 证据，由下次启动按恢复协议处理；长任务仍会取消。
        if self._tasks:
            await asyncio.wait(list(self._tasks.values()), timeout=0.05)
        # done callback 由事件循环稍后调度；先剔除已经结束的 Task，不能把一次
        # 已发生的异常退出误写成用户取消。遗留 running Run 会在下次启动时中断。
        for run_id, task in list(self._tasks.items()):
            if task.done():
                self._forget(run_id, task)
        run_ids = list(self._tasks)
        for run_id in run_ids:
            try:
                await self.cancel(run_id)
            except RunNotFound:
                continue
        if self._tasks:
            await asyncio.gather(*list(self._tasks.values()), return_exceptions=True)
        if self._cleanup_tasks:
            await asyncio.gather(*list(self._cleanup_tasks), return_exceptions=True)
        if self.subagents is not None:
            await self.subagents.close()
