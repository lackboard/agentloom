"""Run 入场、状态迁移、展示投影和持久化事件。"""

import asyncio
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from agentloom.persistence.events import append_run_event
from agentloom.persistence.models import (
    ApprovalRow,
    ArtifactRow,
    MessageRow,
    RunEventRow,
    RunRow,
    ThreadRow,
    TraceSpanRow,
)


class ThreadNotFound(Exception):
    """The requested Thread does not exist."""


class RequestConflict(Exception):
    """The same client request ID was reused with different content."""


class ThreadBusy(Exception):
    """The Thread is archived or already owns an unfinished Run."""


class RunNotFound(Exception):
    """指定的 Run 不存在。"""


class AttachmentNotFound(Exception):
    """提交的附件不存在、不是上传快照或不属于当前线程。"""


@dataclass(frozen=True)
class EventDraft:
    """尚未分配持久化序号的运行事件。"""

    event_type: str
    data: dict
    scope: str = "lead"


@dataclass(frozen=True)
class MessageProjection:
    """一次图消息的 UI 投影及其紧随事件。"""

    id: str
    role: str
    content: dict
    events: tuple[EventDraft, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class UsageTotals:
    """一个 Run 截止当前可确认的模型与工具计量。"""

    model_attempts: int = 0
    tool_executions: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    complete: bool = True


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class RunManager:
    """Own short application transactions for Thread and Run admission."""

    def __init__(
        self,
        sessions: async_sessionmaker,
        *,
        model_name: str,
        config_snapshot: dict | None = None,
        budget: dict | None = None,
        event_notifier: Callable[[str], None] | None = None,
    ):
        self.sessions = sessions
        self.model_name = model_name
        self.config_snapshot_json = _json(config_snapshot or {})
        self.budget_json = _json(budget or {})
        self.event_notifier = event_notifier
        # 模型与工具 callback 可能并发写 span/增量；SQLite 没有行级锁，
        # 因此只串行化这些很短的事件事务，不阻塞模型和工具本身。
        self._live_write_lock = asyncio.Lock()

    def _notify(self, run_id: str) -> None:
        """事务提交后只负责唤醒订阅者；事件真相仍在数据库中。"""
        if self.event_notifier is not None:
            self.event_notifier(run_id)

    @staticmethod
    async def _append_event(session, run: RunRow, draft: EventDraft) -> None:
        await append_run_event(
            session,
            run_id=run.id,
            event_type=draft.event_type,
            scope=draft.scope,
            payload_json=_json(draft.data),
            created_at=_now(),
        )

    @staticmethod
    def _usage_event(usage: UsageTotals) -> EventDraft:
        return EventDraft(
            "usage.updated",
            {
                "model_attempts": usage.model_attempts,
                "tool_executions": usage.tool_executions,
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "complete": usage.complete,
            },
        )

    @staticmethod
    def root_span_id(run_id: str) -> str:
        return f"run:{run_id}"

    @staticmethod
    def _span_data(span: TraceSpanRow) -> dict:
        return {
            "span_id": span.id,
            "trace_id": span.trace_id,
            "parent_span_id": span.parent_span_id,
            "kind": span.kind,
            "name": span.name,
            "status": span.status,
            "attributes": json.loads(span.attributes_json),
            "started_at": span.started_at,
            "finished_at": span.finished_at,
            "duration_ms": span.duration_ms,
            "error_code": span.error_code,
        }

    async def append_message_delta(self, run_id: str, message_id: str, delta: str) -> bool:
        """把已经合并的小文本批次作为持久事件写入；空批次不会占用序号。"""
        if not delta:
            return False
        async with self._live_write_lock:
            async with self.sessions.begin() as session:
                run = await session.get(RunRow, run_id)
                if run is None:
                    raise RunNotFound(run_id)
                if run.status != "running":
                    return False
                await self._append_event(
                    session,
                    run,
                    EventDraft(
                        "message.delta",
                        {"message_id": message_id, "role": "assistant", "delta": delta, "status": "partial"},
                    ),
                )
        self._notify(run_id)
        return True

    async def start_trace_span(
        self,
        run_id: str,
        *,
        span_id: str,
        parent_span_id: str | None,
        kind: str,
        name: str,
        attributes: dict | None = None,
    ) -> None:
        """幂等开始一个安全 Span，并将同一事实写入可重连事件流。"""
        async with self._live_write_lock:
            async with self.sessions.begin() as session:
                run = await session.get(RunRow, run_id)
                if run is None:
                    raise RunNotFound(run_id)
                existing = await session.get(TraceSpanRow, span_id)
                if existing is not None:
                    return
                span = TraceSpanRow(
                    id=span_id,
                    trace_id=run.trace_id,
                    run_id=run.id,
                    parent_span_id=parent_span_id,
                    kind=kind,
                    name=name[:200],
                    status="running",
                    attributes_json=_json(attributes or {}),
                    started_at=_now(),
                    finished_at=None,
                    duration_ms=None,
                    error_code=None,
                )
                session.add(span)
                await session.flush()
                await self._append_event(session, run, EventDraft("trace.span.started", self._span_data(span)))
        self._notify(run_id)

    async def finish_trace_span(
        self,
        run_id: str,
        *,
        span_id: str,
        status: str,
        attributes: dict | None = None,
        error_code: str | None = None,
    ) -> None:
        """幂等结束一个 Span；只合并安全属性，不保存模型或工具正文。"""
        async with self._live_write_lock:
            async with self.sessions.begin() as session:
                run = await session.get(RunRow, run_id)
                span = await session.get(TraceSpanRow, span_id)
                if run is None or span is None or span.run_id != run_id or span.finished_at is not None:
                    return
                finished_at = _now()
                started = datetime.fromisoformat(span.started_at)
                finished = datetime.fromisoformat(finished_at)
                merged = json.loads(span.attributes_json)
                merged.update(attributes or {})
                span.status = status
                span.attributes_json = _json(merged)
                span.finished_at = finished_at
                span.duration_ms = max(0, int((finished - started).total_seconds() * 1000))
                span.error_code = error_code
                await session.flush()
                await self._append_event(session, run, EventDraft("trace.span.finished", self._span_data(span)))
        self._notify(run_id)

    async def start_root_trace(self, run_id: str) -> None:
        run = await self.get_run(run_id)
        if run is None:
            raise RunNotFound(run_id)
        await self.start_trace_span(
            run_id,
            span_id=self.root_span_id(run_id),
            parent_span_id=None,
            kind="run",
            name="agentloom.run",
            attributes={"model": run.model_name},
        )

    async def get_trace_spans(self, run_id: str) -> list[TraceSpanRow]:
        async with self.sessions() as session:
            if await session.get(RunRow, run_id) is None:
                raise RunNotFound(run_id)
            rows = await session.scalars(
                select(TraceSpanRow)
                .where(TraceSpanRow.run_id == run_id)
                .order_by(TraceSpanRow.started_at, TraceSpanRow.id)
            )
            return list(rows)

    async def _finish_root_trace_in_transaction(
        self,
        session,
        run: RunRow,
        *,
        status: str,
        error_code: str | None = None,
    ) -> None:
        """让根 Span 终态与 Run 终态共享事务，避免时间线看见半套结果。"""
        span = await session.get(TraceSpanRow, self.root_span_id(run.id))
        if span is None or span.finished_at is not None:
            return
        finished_at = _now()
        started = datetime.fromisoformat(span.started_at)
        finished = datetime.fromisoformat(finished_at)
        span.status = status
        span.finished_at = finished_at
        span.duration_ms = max(0, int((finished - started).total_seconds() * 1000))
        span.error_code = error_code
        await session.flush()
        await self._append_event(session, run, EventDraft("trace.span.finished", self._span_data(span)))

    async def create_thread(self, *, title: str = "New thread", profile: str = "default") -> ThreadRow:
        now = _now()
        row = ThreadRow(id=str(uuid4()), title=title, agent_profile=profile, created_at=now, updated_at=now)
        async with self.sessions.begin() as session:
            session.add(row)
        return row

    async def list_threads(self, *, limit: int = 100) -> list[tuple[ThreadRow, RunRow | None]]:
        """返回最近活跃线程及各自最新 Run，供工作台恢复页面。"""
        async with self.sessions() as session:
            threads = list(
                await session.scalars(
                    select(ThreadRow)
                    .where(ThreadRow.archived_at.is_(None))
                    .order_by(ThreadRow.updated_at.desc(), ThreadRow.created_at.desc())
                    .limit(limit)
                )
            )
            if not threads:
                return []
            runs = list(
                await session.scalars(
                    select(RunRow)
                    .where(RunRow.thread_id.in_([thread.id for thread in threads]))
                    .order_by(RunRow.created_at.desc())
                )
            )
        latest: dict[str, RunRow] = {}
        for run in runs:
            latest.setdefault(run.thread_id, run)
        return [(thread, latest.get(thread.id)) for thread in threads]

    async def get_thread(self, thread_id: str) -> tuple[ThreadRow, RunRow | None]:
        async with self.sessions() as session:
            thread = await session.get(ThreadRow, thread_id)
            if thread is None:
                raise ThreadNotFound(thread_id)
            latest_run = await session.scalar(
                select(RunRow).where(RunRow.thread_id == thread_id).order_by(RunRow.created_at.desc()).limit(1)
            )
            return thread, latest_run

    async def submit(
        self,
        thread_id: str,
        *,
        text: str,
        client_request_id: str,
        attachment_ids: list[str] | None = None,
    ) -> RunRow:
        """Persist a pending Run, stable input message and first event atomically."""
        attachment_ids = list(dict.fromkeys(attachment_ids or []))
        body = {"text": text, "attachment_ids": attachment_ids}
        body_json = _json(body)
        request_hash = hashlib.sha256(body_json.encode("utf-8")).hexdigest()
        try:
            async with self.sessions.begin() as session:
                thread = await session.get(ThreadRow, thread_id)
                if thread is None:
                    raise ThreadNotFound(thread_id)
                if thread.archived_at is not None:
                    raise ThreadBusy(thread_id)
                attachments = []
                if attachment_ids:
                    attachments = list(
                        await session.scalars(
                            select(ArtifactRow).where(
                                ArtifactRow.id.in_(attachment_ids),
                                ArtifactRow.thread_id == thread_id,
                                ArtifactRow.kind == "upload",
                            )
                        )
                    )
                    by_id = {row.id: row for row in attachments}
                    if set(by_id) != set(attachment_ids):
                        raise AttachmentNotFound(thread_id)
                    attachments = [by_id[artifact_id] for artifact_id in attachment_ids]
                existing = await session.scalar(
                    select(RunRow).where(
                        RunRow.thread_id == thread_id,
                        RunRow.client_request_id == client_request_id,
                    )
                )
                if existing is not None:
                    if existing.request_hash != request_hash:
                        raise RequestConflict(client_request_id)
                    return existing

                now = _now()
                thread.updated_at = now
                run_id = str(uuid4())
                input_id = str(uuid4())
                next_message_seq = 1 + (
                    await session.scalar(select(func.max(MessageRow.seq)).where(MessageRow.thread_id == thread_id)) or 0
                )
                row = RunRow(
                    id=run_id,
                    trace_id=uuid4().hex,
                    thread_id=thread_id,
                    client_request_id=client_request_id,
                    request_hash=request_hash,
                    input_json=_json(
                        {
                            **body,
                            "attachments": [
                                {
                                    "id": artifact.id,
                                    "display_name": artifact.display_name,
                                    "virtual_path": f"/mnt/user-data/{artifact.relative_path}",
                                    "mime_type": artifact.mime_type,
                                    "sha256": artifact.sha256,
                                }
                                for artifact in attachments
                            ],
                        }
                    ),
                    input_message_id=input_id,
                    status="pending",
                    model_name=self.model_name,
                    config_snapshot_json=self.config_snapshot_json,
                    budget_json=self.budget_json,
                    next_event_seq=2,
                    created_at=now,
                )
                session.add(row)
                await session.flush()
                session.add(
                    MessageRow(
                        id=input_id,
                        thread_id=thread_id,
                        run_id=run_id,
                        seq=next_message_seq,
                        graph_message_id=input_id,
                        role="user",
                        content_json=_json({"text": text, "attachment_ids": attachment_ids}),
                        created_at=now,
                    )
                )
                session.add(
                    RunEventRow(
                        run_id=run_id,
                        seq=1,
                        event_type="message.completed",
                        scope="lead",
                        payload_json=_json(
                            {
                                "message_id": input_id,
                                "role": "user",
                                "content": {"text": text, "attachment_ids": attachment_ids},
                                "status": "completed",
                            }
                        ),
                        created_at=now,
                    )
                )
                await session.flush()
        except IntegrityError as exc:
            if "UNIQUE constraint failed: runs." not in str(exc):
                raise
            async with self.sessions() as session:
                existing = await session.scalar(
                    select(RunRow).where(
                        RunRow.thread_id == thread_id,
                        RunRow.client_request_id == client_request_id,
                    )
                )
                if existing is not None:
                    if existing.request_hash != request_hash:
                        raise RequestConflict(client_request_id) from None
                    return existing
            raise ThreadBusy(thread_id) from None
        self._notify(row.id)
        return row

    async def try_start(self, run_id: str) -> bool:
        """用条件更新取得执行权，并在同一事务写入 run.started。"""
        now = _now()
        async with self.sessions.begin() as session:
            result = await session.execute(
                update(RunRow)
                .where(RunRow.id == run_id, RunRow.status == "pending")
                .values(status="running", started_at=now)
            )
            if result.rowcount != 1:
                return False
            run = await session.get(RunRow, run_id)
            assert run is not None
            await self._append_event(session, run, EventDraft("run.started", {"status": "running"}))
        self._notify(run_id)
        return True

    async def wait_for_approval(
        self,
        run_id: str,
        approval_id: str,
        checkpoint_id: str,
        *,
        usage: UsageTotals,
    ) -> bool:
        """确认 interrupt checkpoint 后，原子开放审批并把 Run 置为等待。"""
        async with self.sessions.begin() as session:
            approval = await session.get(ApprovalRow, approval_id)
            if approval is None or approval.run_id != run_id or approval.status != "pending":
                return False
            result = await session.execute(
                update(RunRow)
                .where(RunRow.id == run_id, RunRow.status == "running")
                .values(
                    status="waiting_input",
                    last_checkpoint_id=checkpoint_id,
                    model_attempts=usage.model_attempts,
                    tool_executions_count=usage.tool_executions,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    usage_complete=int(usage.complete),
                )
            )
            if result.rowcount != 1:
                return False
            approval.checkpoint_id = checkpoint_id
            run = await session.get(RunRow, run_id, populate_existing=True)
            assert run is not None
            await self._append_event(session, run, self._usage_event(usage))
            await self._append_event(
                session,
                run,
                EventDraft(
                    "approval.required",
                    {
                        "approval_id": approval.id,
                        "kind": approval.kind,
                        "payload_hash": approval.payload_hash,
                        "payload": json.loads(approval.payload_json),
                    },
                ),
            )
        self._notify(run_id)
        return True

    async def try_resume(self, run_id: str) -> bool:
        """只有 waiting_input Run 能取得一次恢复执行权。"""
        async with self.sessions.begin() as session:
            result = await session.execute(
                update(RunRow).where(RunRow.id == run_id, RunRow.status == "waiting_input").values(status="running")
            )
        return result.rowcount == 1

    async def interrupt_orphaned_runs(self, run_ids: set[str]) -> int:
        """进程启动时把含不明工具结果的遗留 running Run 转为可人工恢复状态。"""
        changed: list[str] = []
        async with self.sessions.begin() as session:
            for run_id in run_ids:
                result = await session.execute(
                    update(RunRow)
                    .where(RunRow.id == run_id, RunRow.status == "running")
                    .values(
                        status="interrupted",
                        stop_reason="process_restarted",
                        error_code="TOOL_RESULT_UNCERTAIN",
                        error_message="进程在工具执行期间退出；请核验或放弃 uncertain 结果后恢复",
                    )
                )
                if result.rowcount == 1:
                    run = await session.get(RunRow, run_id, populate_existing=True)
                    assert run is not None
                    await self._append_event(
                        session,
                        run,
                        EventDraft(
                            "run.interrupted",
                            {"status": "interrupted", "reason": "tool_result_uncertain"},
                        ),
                    )
                    changed.append(run_id)
        for run_id in changed:
            self._notify(run_id)
        return len(changed)

    async def try_recover(self, run_id: str) -> bool:
        """只有 interrupted Run 能以条件更新取得一次恢复执行权。"""
        async with self.sessions.begin() as session:
            result = await session.execute(
                update(RunRow)
                .where(RunRow.id == run_id, RunRow.status == "interrupted")
                .values(status="running", stop_reason=None, error_code=None, error_message=None)
            )
            if result.rowcount == 1:
                run = await session.get(RunRow, run_id, populate_existing=True)
                assert run is not None
                await self._append_event(session, run, EventDraft("run.recovered", {"status": "running"}))
        if result.rowcount == 1:
            self._notify(run_id)
        return result.rowcount == 1

    async def complete_success(
        self,
        run_id: str,
        *,
        messages: list[MessageProjection],
        usage: UsageTotals,
        events: list[EventDraft] | None = None,
    ) -> bool:
        """仅允许 running 赢得成功终态，同时提交消息、计量和终态事件。"""
        now = _now()
        async with self.sessions.begin() as session:
            result = await session.execute(
                update(RunRow)
                .where(RunRow.id == run_id, RunRow.status == "running")
                .values(
                    status="succeeded",
                    stop_reason="completed",
                    model_attempts=usage.model_attempts,
                    tool_executions_count=usage.tool_executions,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    usage_complete=int(usage.complete),
                    finished_at=now,
                )
            )
            if result.rowcount != 1:
                return False
            run = await session.get(RunRow, run_id)
            assert run is not None
            next_message_seq = 1 + (
                await session.scalar(select(func.max(MessageRow.seq)).where(MessageRow.thread_id == run.thread_id)) or 0
            )
            for projection in messages:
                session.add(
                    MessageRow(
                        id=projection.id,
                        thread_id=run.thread_id,
                        run_id=run.id,
                        seq=next_message_seq,
                        graph_message_id=projection.id,
                        role=projection.role,
                        content_json=_json(projection.content),
                        created_at=now,
                    )
                )
                next_message_seq += 1
                await self._append_event(
                    session,
                    run,
                    EventDraft(
                        "message.completed",
                        {
                            "message_id": projection.id,
                            "role": projection.role,
                            "content": projection.content,
                            "status": "completed",
                        },
                    ),
                )
                for draft in projection.events:
                    await self._append_event(session, run, draft)
            for draft in events or []:
                await self._append_event(session, run, draft)
            await self._append_event(session, run, self._usage_event(usage))
            await self._finish_root_trace_in_transaction(session, run, status="succeeded")
            await self._append_event(
                session,
                run,
                EventDraft("run.finished", {"status": "succeeded", "stop_reason": "completed"}),
            )
            thread = await session.get(ThreadRow, run.thread_id)
            if thread is not None:
                thread.updated_at = now
        self._notify(run_id)
        return True

    async def archive_messages(self, run_id: str, messages: list[MessageProjection]) -> int:
        """压缩前幂等保存将被移出 checkpoint 上下文的 UI 消息。"""
        if not messages:
            return 0
        inserted = 0
        async with self.sessions.begin() as session:
            run = await session.get(RunRow, run_id)
            if run is None:
                raise RunNotFound(run_id)
            existing = set(
                await session.scalars(select(MessageRow.graph_message_id).where(MessageRow.thread_id == run.thread_id))
            )
            next_message_seq = 1 + (
                await session.scalar(select(func.max(MessageRow.seq)).where(MessageRow.thread_id == run.thread_id)) or 0
            )
            for projection in messages:
                if projection.id in existing:
                    continue
                session.add(
                    MessageRow(
                        id=projection.id,
                        thread_id=run.thread_id,
                        run_id=run.id,
                        seq=next_message_seq,
                        graph_message_id=projection.id,
                        role=projection.role,
                        content_json=_json(projection.content),
                        created_at=_now(),
                    )
                )
                existing.add(projection.id)
                next_message_seq += 1
                inserted += 1
                await self._append_event(
                    session,
                    run,
                    EventDraft(
                        "message.completed",
                        {
                            "message_id": projection.id,
                            "role": projection.role,
                            "content": projection.content,
                            "status": "completed",
                        },
                    ),
                )
        if inserted:
            self._notify(run_id)
        return inserted

    async def complete_failure(
        self,
        run_id: str,
        *,
        error: Exception,
        usage: UsageTotals,
        events: list[EventDraft] | None = None,
    ) -> bool:
        """模型或图失败时保留稳定错误，不把失败写成 succeeded。"""
        now = _now()
        message = f"{type(error).__name__}: {error}"
        async with self.sessions.begin() as session:
            result = await session.execute(
                update(RunRow)
                .where(RunRow.id == run_id, RunRow.status == "running")
                .values(
                    status="failed",
                    stop_reason="error",
                    error_code="AGENT_EXECUTION_FAILED",
                    error_message=message,
                    model_attempts=usage.model_attempts,
                    tool_executions_count=usage.tool_executions,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    usage_complete=int(usage.complete),
                    finished_at=now,
                )
            )
            if result.rowcount != 1:
                return False
            run = await session.get(RunRow, run_id)
            assert run is not None
            for draft in events or []:
                await self._append_event(session, run, draft)
            await self._append_event(session, run, self._usage_event(usage))
            await self._finish_root_trace_in_transaction(
                session,
                run,
                status="failed",
                error_code="AGENT_EXECUTION_FAILED",
            )
            await self._append_event(
                session,
                run,
                EventDraft(
                    "run.finished",
                    {
                        "status": "failed",
                        "stop_reason": "error",
                        "error": {"code": "AGENT_EXECUTION_FAILED", "message": message},
                    },
                ),
            )
        self._notify(run_id)
        return True

    async def request_cancel(self, run_id: str) -> str:
        """幂等请求取消；终态与 cancelling 都原样返回。"""
        async with self.sessions.begin() as session:
            if await session.get(RunRow, run_id) is None:
                raise RunNotFound(run_id)
            await session.execute(
                update(RunRow)
                .where(
                    RunRow.id == run_id,
                    RunRow.status.in_(("pending", "running", "waiting_input", "interrupted")),
                )
                .values(status="cancelling", stop_reason="user_cancelled")
            )
            run = await session.get(RunRow, run_id, populate_existing=True)
            assert run is not None
            status = run.status
        return status

    async def finish_cancel(
        self,
        run_id: str,
        *,
        usage: UsageTotals,
        messages: list[MessageProjection] | None = None,
    ) -> bool:
        """只有已接受取消的 Run 才能进入 cancelled，并投影补齐的工具失败消息。"""
        now = _now()
        async with self.sessions.begin() as session:
            result = await session.execute(
                update(RunRow)
                .where(RunRow.id == run_id, RunRow.status == "cancelling")
                .values(
                    status="cancelled",
                    stop_reason="user_cancelled",
                    model_attempts=usage.model_attempts,
                    tool_executions_count=usage.tool_executions,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    usage_complete=int(usage.complete),
                    finished_at=now,
                )
            )
            if result.rowcount != 1:
                return False
            run = await session.get(RunRow, run_id)
            assert run is not None
            next_message_seq = 1 + (
                await session.scalar(select(func.max(MessageRow.seq)).where(MessageRow.thread_id == run.thread_id)) or 0
            )
            for projection in messages or []:
                session.add(
                    MessageRow(
                        id=projection.id,
                        thread_id=run.thread_id,
                        run_id=run.id,
                        seq=next_message_seq,
                        graph_message_id=projection.id,
                        role=projection.role,
                        content_json=_json(projection.content),
                        created_at=now,
                    )
                )
                next_message_seq += 1
                await self._append_event(
                    session,
                    run,
                    EventDraft(
                        "message.completed",
                        {
                            "message_id": projection.id,
                            "role": projection.role,
                            "content": projection.content,
                            "status": "completed",
                        },
                    ),
                )
            await self._append_event(session, run, self._usage_event(usage))
            await self._finish_root_trace_in_transaction(session, run, status="cancelled", error_code="RUN_CANCELLED")
            await self._append_event(
                session,
                run,
                EventDraft("run.finished", {"status": "cancelled", "stop_reason": "user_cancelled"}),
            )
        self._notify(run_id)
        return True

    async def get_run(self, run_id: str) -> RunRow | None:
        async with self.sessions() as session:
            return await session.get(RunRow, run_id)

    async def get_messages(self, thread_id: str) -> list[MessageRow]:
        async with self.sessions() as session:
            if await session.get(ThreadRow, thread_id) is None:
                raise ThreadNotFound(thread_id)
            result = await session.scalars(
                select(MessageRow).where(MessageRow.thread_id == thread_id).order_by(MessageRow.seq)
            )
            return list(result)

    async def get_events(self, run_id: str) -> list[RunEventRow]:
        async with self.sessions() as session:
            result = await session.scalars(
                select(RunEventRow).where(RunEventRow.run_id == run_id).order_by(RunEventRow.seq)
            )
            return list(result)

    async def get_events_after(self, run_id: str, after_seq: int, *, limit: int = 100) -> list[RunEventRow]:
        """按 Run 内序号回放一页事件。"""
        async with self.sessions() as session:
            result = await session.scalars(
                select(RunEventRow)
                .where(RunEventRow.run_id == run_id, RunEventRow.seq > after_seq)
                .order_by(RunEventRow.seq)
                .limit(limit)
            )
            return list(result)
