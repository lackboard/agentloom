"""子任务生命周期在 app.sqlite 中的短事务实现。"""

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from agentloom.persistence.models import RunEventRow, RunRow, SubagentTaskRow
from agentloom.runtime.manager import EventDraft
from agentloom.subagents.contracts import AgentType, SubagentResult


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class SubagentTaskConflict(RuntimeError):
    """同一个父工具调用被换成了另一份子任务。"""

    code = "SUBAGENT_TASK_CONFLICT"


class SubagentLimitExceeded(RuntimeError):
    """本 Run 已达到允许创建的子任务总数。"""

    code = "SUBAGENT_LIMIT_EXCEEDED"


@dataclass(frozen=True)
class SubagentTaskRecord:
    id: str
    run_id: str
    parent_tool_call_id: str
    agent_type: AgentType
    status: str
    prompt: str
    result: dict | None
    deadline_at: str

    @classmethod
    def from_row(cls, row: SubagentTaskRow) -> "SubagentTaskRecord":
        return cls(
            id=row.id,
            run_id=row.run_id,
            parent_tool_call_id=row.parent_tool_call_id,
            agent_type=row.agent_type,
            status=row.status,
            prompt=row.prompt,
            result=None if row.result_json is None else json.loads(row.result_json),
            deadline_at=row.deadline_at,
        )


class SubagentTaskRepository:
    """用唯一键绑定父 tool_call_id，并把状态和事件一起提交。"""

    def __init__(self, sessions: async_sessionmaker, *, event_notifier=None) -> None:
        self.sessions = sessions
        self.event_notifier = event_notifier
        # SQLite 没有行级锁；子任务会并发推进并共同分配 run_event.seq。
        # 这里只串行化很短的数据库事务，模型和工具执行仍然保持并发。
        self._write_lock = asyncio.Lock()

    @staticmethod
    def _append_event(session, run: RunRow, draft: EventDraft) -> None:
        seq = run.next_event_seq
        run.next_event_seq += 1
        session.add(
            RunEventRow(
                run_id=run.id,
                seq=seq,
                event_type=draft.event_type,
                scope=draft.scope,
                payload_json=_json(draft.data),
                created_at=_now(),
            )
        )

    def _notify(self, run_id: str) -> None:
        if self.event_notifier is not None:
            self.event_notifier(run_id)

    async def list_for_run(self, run_id: str) -> list[SubagentTaskRecord]:
        async with self.sessions() as session:
            rows = await session.scalars(
                select(SubagentTaskRow)
                .where(SubagentTaskRow.run_id == run_id)
                .order_by(SubagentTaskRow.created_at, SubagentTaskRow.id)
            )
            return [SubagentTaskRecord.from_row(row) for row in rows]

    async def prepare(
        self,
        run_id: str,
        parent_tool_call_id: str,
        agent_type: AgentType,
        prompt: str,
        *,
        timeout_seconds: float,
        expected_outputs: list[str],
        max_tasks_per_run: int,
    ) -> SubagentTaskRecord:
        async with self._write_lock:
            async with self.sessions.begin() as session:
                existing = await session.scalar(
                    select(SubagentTaskRow).where(
                        SubagentTaskRow.run_id == run_id,
                        SubagentTaskRow.parent_tool_call_id == parent_tool_call_id,
                    )
                )
                if existing is not None:
                    if existing.agent_type != agent_type or existing.prompt != prompt:
                        raise SubagentTaskConflict("同一个 parent_tool_call_id 不能更换角色或任务说明")
                    return SubagentTaskRecord.from_row(existing)
                run = await session.get(RunRow, run_id)
                if run is None or run.status != "running":
                    raise SubagentTaskConflict("只有 running Run 可以创建子任务")
                task_count = await session.scalar(
                    select(func.count(SubagentTaskRow.id)).where(SubagentTaskRow.run_id == run_id)
                )
                if int(task_count or 0) >= max_tasks_per_run:
                    raise SubagentLimitExceeded(f"每个 Run 最多创建 {max_tasks_per_run} 个子任务")
                task_id = str(uuid4())
                now = datetime.now(UTC)
                row = SubagentTaskRow(
                    id=task_id,
                    run_id=run_id,
                    parent_tool_call_id=parent_tool_call_id,
                    agent_type=agent_type,
                    status="queued",
                    prompt=prompt,
                    result_json=None,
                    acceptance_json=_json({"expected_outputs": expected_outputs, "tests_passed": "unverified"}),
                    input_tokens=0,
                    output_tokens=0,
                    usage_complete=1,
                    created_at=now.isoformat(),
                    started_at=None,
                    finished_at=None,
                    deadline_at=(now + timedelta(seconds=timeout_seconds)).isoformat(),
                )
                session.add(row)
                await session.flush()
                self._append_event(
                    session,
                    run,
                    EventDraft(
                        "subagent.queued",
                        {"task_id": task_id, "agent_type": agent_type, "status": "queued"},
                        scope=f"subagent:{task_id}",
                    ),
                )
        self._notify(run_id)
        return SubagentTaskRecord.from_row(row)

    async def start(self, task_id: str) -> bool:
        async with self._write_lock:
            async with self.sessions.begin() as session:
                result = await session.execute(
                    update(SubagentTaskRow)
                    .where(SubagentTaskRow.id == task_id, SubagentTaskRow.status == "queued")
                    .values(status="running", started_at=_now())
                )
                row = await session.get(SubagentTaskRow, task_id, populate_existing=True)
                if row is None or result.rowcount != 1:
                    return False
                run = await session.get(RunRow, row.run_id)
                assert run is not None
                self._append_event(
                    session,
                    run,
                    EventDraft(
                        "subagent.started",
                        {"task_id": row.id, "agent_type": row.agent_type, "status": "running"},
                        scope=f"subagent:{row.id}",
                    ),
                )
        self._notify(row.run_id)
        return True

    async def finish(
        self,
        result_value: SubagentResult,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        usage_complete: bool = True,
    ) -> bool:
        payload = result_value.model_dump(mode="json")
        async with self._write_lock:
            async with self.sessions.begin() as session:
                changed = await session.execute(
                    update(SubagentTaskRow)
                    .where(
                        SubagentTaskRow.id == result_value.task_id,
                        SubagentTaskRow.status.in_(("queued", "running")),
                    )
                    .values(
                        status=result_value.status,
                        result_json=_json(payload),
                        acceptance_json=_json(result_value.acceptance),
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        usage_complete=int(usage_complete),
                        finished_at=_now(),
                    )
                )
                row = await session.get(SubagentTaskRow, result_value.task_id, populate_existing=True)
                if row is None or changed.rowcount != 1:
                    return False
                run = await session.get(RunRow, row.run_id)
                assert run is not None
                self._append_event(
                    session,
                    run,
                    EventDraft(
                        "subagent.finished",
                        {
                            "task_id": row.id,
                            "agent_type": row.agent_type,
                            "status": result_value.status,
                            "summary": result_value.summary[:1000],
                        },
                        scope=f"subagent:{row.id}",
                    ),
                )
        self._notify(row.run_id)
        return True

    async def cancel_open_for_run(self, run_id: str) -> int:
        """取消仍在排队或执行的子任务，并为每项写入可回放终态事件。"""
        changed = 0
        async with self._write_lock:
            async with self.sessions.begin() as session:
                rows = list(
                    await session.scalars(
                        select(SubagentTaskRow).where(
                            SubagentTaskRow.run_id == run_id,
                            SubagentTaskRow.status.in_(("queued", "running")),
                        )
                    )
                )
                run = await session.get(RunRow, run_id)
                if run is None:
                    return 0
                for row in rows:
                    result = SubagentResult(
                        task_id=row.id,
                        agent_type=row.agent_type,
                        status="cancelled",
                        summary="父 Run 已取消，子任务已收尾",
                        acceptance={"tests_passed": "unverified"},
                        error={"code": "RUN_CANCELLED", "message": "父 Run 已取消"},
                    )
                    row.status = "cancelled"
                    row.result_json = _json(result.model_dump(mode="json"))
                    row.acceptance_json = _json(result.acceptance)
                    row.finished_at = _now()
                    self._append_event(
                        session,
                        run,
                        EventDraft(
                            "subagent.finished",
                            {"task_id": row.id, "agent_type": row.agent_type, "status": "cancelled"},
                            scope=f"subagent:{row.id}",
                        ),
                    )
                    changed += 1
        if changed:
            self._notify(run_id)
        return changed

    async def interrupt_orphaned(self) -> set[str]:
        """启动时终止遗留子图；V1 不假装从 child graph 中途恢复。"""
        run_ids: set[str] = set()
        async with self._write_lock:
            async with self.sessions.begin() as session:
                rows = list(
                    await session.scalars(
                        select(SubagentTaskRow).where(SubagentTaskRow.status.in_(("queued", "running")))
                    )
                )
                for row in rows:
                    run = await session.get(RunRow, row.run_id)
                    if run is None:
                        continue
                    result = SubagentResult(
                        task_id=row.id,
                        agent_type=row.agent_type,
                        status="interrupted",
                        summary="服务重启，中途子 Agent 图不会自动恢复",
                        acceptance={"tests_passed": "unverified"},
                        error={"code": "PROCESS_RESTARTED", "message": "子任务执行期间服务重启"},
                    )
                    row.status = "interrupted"
                    row.result_json = _json(result.model_dump(mode="json"))
                    row.acceptance_json = _json(result.acceptance)
                    row.finished_at = _now()
                    self._append_event(
                        session,
                        run,
                        EventDraft(
                            "subagent.finished",
                            {"task_id": row.id, "agent_type": row.agent_type, "status": "interrupted"},
                            scope=f"subagent:{row.id}",
                        ),
                    )
                    run_ids.add(row.run_id)
        for run_id in run_ids:
            self._notify(run_id)
        return run_ids
