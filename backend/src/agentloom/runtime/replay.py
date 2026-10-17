"""终态 Run 的历史证据回放与可核对比较。"""

import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from agentloom.persistence.models import (
    ArtifactRow,
    MessageRow,
    RunEventRow,
    RunReplayRow,
    RunRow,
    ToolExecutionRow,
    TraceSpanRow,
)
from agentloom.runtime.ledger import canonical_json

TERMINAL_RUNS = {"succeeded", "failed", "cancelled"}
TERMINAL_TOOLS = {"succeeded", "failed", "denied", "cancelled", "skipped", "verified"}


class ReplayError(RuntimeError):
    code = "REPLAY_ERROR"


class ReplayNotFound(ReplayError):
    code = "RUN_NOT_FOUND"


class ReplayUnsafe(ReplayError):
    code = "REPLAY_EVIDENCE_INCOMPLETE"


@dataclass(frozen=True)
class ReplayRecord:
    id: str
    source_run_id: str
    evidence_hash: str
    evidence: dict[str, Any]
    status: str
    created_at: str

    @classmethod
    def from_row(cls, row: RunReplayRow) -> "ReplayRecord":
        return cls(
            row.id, row.source_run_id, row.evidence_hash, json.loads(row.evidence_json), row.status, row.created_at
        )


def _now() -> str:
    return datetime.now(UTC).isoformat()


class ReplayService:
    """只回放已持久化事实；绝不重新请求模型或调用工具。"""

    def __init__(self, sessions: async_sessionmaker) -> None:
        self.sessions = sessions
        self._create_lock = asyncio.Lock()

    async def create(self, run_id: str) -> ReplayRecord:
        # 单进程先串行化“查重 + 插入”，数据库唯一键仍作为最终防线。
        async with self._create_lock:
            return await self._create(run_id)

    async def _create(self, run_id: str) -> ReplayRecord:
        async with self.sessions.begin() as session:
            run = await session.get(RunRow, run_id)
            if run is None:
                raise ReplayNotFound("Run 不存在")
            if run.status not in TERMINAL_RUNS:
                raise ReplayUnsafe("只有终态 Run 可以冻结回放证据")
            tools = list(
                await session.scalars(
                    select(ToolExecutionRow)
                    .where(ToolExecutionRow.run_id == run_id)
                    .order_by(ToolExecutionRow.created_at)
                )
            )
            unsafe = [tool.id for tool in tools if tool.status not in TERMINAL_TOOLS or tool.result_json is None]
            if unsafe:
                raise ReplayUnsafe(f"工具证据尚未确定：{', '.join(unsafe)}")
            messages = list(
                await session.scalars(select(MessageRow).where(MessageRow.run_id == run_id).order_by(MessageRow.seq))
            )
            events = list(
                await session.scalars(select(RunEventRow).where(RunEventRow.run_id == run_id).order_by(RunEventRow.seq))
            )
            evidence = {
                "version": 1,
                "mode": "historical_evidence",
                "will_execute_model": False,
                "will_execute_tools": False,
                "source": {"run_id": run.id, "trace_id": run.trace_id, "status": run.status, "model": run.model_name},
                "messages": [
                    {"id": item.id, "seq": item.seq, "role": item.role, "content": json.loads(item.content_json)}
                    for item in messages
                ],
                "events": [
                    {
                        "seq": item.seq,
                        "type": item.event_type,
                        "scope": item.scope,
                        "data": json.loads(item.payload_json),
                    }
                    for item in events
                ],
                "tool_evidence": [
                    {
                        "execution_id": item.id,
                        "tool_call_id": item.tool_call_id,
                        "tool_name": item.tool_name,
                        "args_hash": item.args_hash,
                        "replay_class": item.replay_class,
                        "status": item.status,
                        "attempts": item.attempts,
                        "result": json.loads(item.result_json or "null"),
                        "result_hash": hashlib.sha256((item.result_json or "null").encode()).hexdigest(),
                        "reused_historical_result": True,
                    }
                    for item in tools
                ],
            }
            evidence_json = canonical_json(evidence)
            digest = hashlib.sha256(evidence_json.encode()).hexdigest()
            existing = await session.scalar(
                select(RunReplayRow).where(RunReplayRow.source_run_id == run_id, RunReplayRow.evidence_hash == digest)
            )
            if existing is not None:
                return ReplayRecord.from_row(existing)
            row = RunReplayRow(
                id=str(uuid4()),
                source_run_id=run_id,
                evidence_hash=digest,
                evidence_json=evidence_json,
                status="completed",
                created_at=_now(),
            )
            session.add(row)
            await session.flush()
            return ReplayRecord.from_row(row)

    async def compare(self, left_id: str, right_id: str) -> dict[str, Any]:
        async with self.sessions() as session:
            left, right = await session.get(RunRow, left_id), await session.get(RunRow, right_id)
            if left is None or right is None:
                raise ReplayNotFound("待比较的 Run 不存在")

            async def facts(run: RunRow) -> dict[str, Any]:
                tools = list(
                    await session.scalars(
                        select(ToolExecutionRow)
                        .where(ToolExecutionRow.run_id == run.id)
                        .order_by(ToolExecutionRow.created_at)
                    )
                )
                spans = list(await session.scalars(select(TraceSpanRow).where(TraceSpanRow.run_id == run.id)))
                artifacts = list(
                    await session.scalars(
                        select(ArtifactRow)
                        .where(ArtifactRow.run_id == run.id)
                        .order_by(ArtifactRow.created_at, ArtifactRow.id)
                    )
                )
                return {
                    "run_id": run.id,
                    "status": run.status,
                    "model": run.model_name,
                    "duration_ms": next((span.duration_ms for span in spans if span.kind == "run"), None),
                    "usage": {
                        "model_attempts": run.model_attempts,
                        "tool_executions": run.tool_executions_count,
                        "input_tokens": run.input_tokens,
                        "output_tokens": run.output_tokens,
                        "complete": bool(run.usage_complete),
                    },
                    "tools": [
                        {
                            "name": item.tool_name,
                            "status": item.status,
                            "args_hash": item.args_hash,
                            "replay_class": item.replay_class,
                        }
                        for item in tools
                    ],
                    "trace": {
                        "span_count": len(spans),
                        "failed_span_count": sum(item.status == "failed" for item in spans),
                    },
                    "artifacts": [
                        {"path": item.relative_path, "sha256": item.sha256, "size_bytes": item.size_bytes}
                        for item in artifacts
                    ],
                }

            left_facts, right_facts = await facts(left), await facts(right)
            numeric = ("model_attempts", "tool_executions", "input_tokens", "output_tokens")
            return {
                "left": left_facts,
                "right": right_facts,
                "delta": {
                    "duration_ms": None
                    if left_facts["duration_ms"] is None or right_facts["duration_ms"] is None
                    else right_facts["duration_ms"] - left_facts["duration_ms"],
                    "usage": {key: right_facts["usage"][key] - left_facts["usage"][key] for key in numeric},
                    "tool_sequence_changed": left_facts["tools"] != right_facts["tools"],
                    "artifact_hashes_changed": left_facts["artifacts"] != right_facts["artifacts"],
                },
            }
