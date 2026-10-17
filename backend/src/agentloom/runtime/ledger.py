"""工具调用的持久化执行账本。"""

import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal
from uuid import uuid4

from langchain_core.messages import ToolMessage
from langgraph.types import Command
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from agentloom.persistence.models import RunRow, ToolExecutionRow

if TYPE_CHECKING:
    from agentloom.sandbox import WorkspaceService

ReplayClass = Literal["read_only", "idempotent", "manual"]


class ToolLedgerError(RuntimeError):
    """带稳定错误码的工具账本错误。"""

    code = "TOOL_LEDGER_ERROR"


class ToolCallConflict(ToolLedgerError):
    """同一个逻辑调用 ID 被换成了其他工具或参数。"""

    code = "TOOL_CALL_CONFLICT"


class ToolResultUncertain(ToolLedgerError):
    """工具可能已经产生副作用，当前不能自动重放。"""

    code = "TOOL_RESULT_UNCERTAIN"


class ToolExecutionNotFound(ToolLedgerError):
    code = "TOOL_EXECUTION_NOT_FOUND"


class ToolResolutionConflict(ToolLedgerError):
    code = "TOOL_RESOLUTION_CONFLICT"


class ToolEvidenceMismatch(ToolLedgerError):
    code = "TOOL_EVIDENCE_MISMATCH"


@dataclass(frozen=True)
class ToolExecutionRecord:
    id: str
    run_id: str
    scope: str
    tool_call_id: str
    tool_name: str
    args_hash: str
    args: dict[str, Any]
    replay_class: str
    status: str
    result: dict[str, Any] | None
    precondition: dict[str, Any] | None
    error_code: str | None
    attempts: int
    created_at: str
    started_at: str | None
    finished_at: str | None

    @classmethod
    def from_row(cls, row: ToolExecutionRow) -> "ToolExecutionRecord":
        return cls(
            id=row.id,
            run_id=row.run_id,
            scope=row.scope,
            tool_call_id=row.tool_call_id,
            tool_name=row.tool_name,
            args_hash=row.args_hash,
            args=json.loads(row.args_json),
            replay_class=row.replay_class,
            status=row.status,
            result=None if row.result_json is None else json.loads(row.result_json),
            precondition=None if row.precondition_json is None else json.loads(row.precondition_json),
            error_code=row.error_code,
            attempts=row.attempts,
            created_at=row.created_at,
            started_at=row.started_at,
            finished_at=row.finished_at,
        )


def _now() -> str:
    return datetime.now(UTC).isoformat()


def canonical_json(value: Any) -> str:
    """生成稳定 JSON；hash、数据库参数和审批必须使用同一种规范化。"""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def arguments_hash(arguments: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(arguments).encode("utf-8")).hexdigest()


def replay_class_for(tool_name: str) -> ReplayClass:
    if tool_name in {"add", "lookup_note", "list_dir", "read_file"}:
        return "read_only"
    if tool_name in {"write_file", "replace_file", "present_files", "task", "remember_preference"}:
        return "idempotent"
    if tool_name.startswith("mcp__"):
        return "read_only"
    return "manual"


def serialize_tool_result(result: ToolMessage | Command) -> dict[str, Any]:
    """只保存当前工具链会返回的 ToolMessage/Command 可重放部分。"""
    if isinstance(result, ToolMessage):
        return {"kind": "tool_message", "message": result.model_dump(mode="json")}
    if not isinstance(result, Command) or not isinstance(result.update, dict):
        raise TypeError(f"不支持保存的工具结果：{type(result).__name__}")
    update_value: dict[str, Any] = {}
    for key, value in result.update.items():
        if key == "messages":
            update_value[key] = [message.model_dump(mode="json") for message in value]
        else:
            update_value[key] = value
    return {"kind": "command", "update": update_value}


def deserialize_tool_result(payload: dict[str, Any]) -> ToolMessage | Command:
    kind = payload.get("kind")
    if kind == "tool_message":
        return ToolMessage.model_validate(payload["message"])
    if kind == "command":
        update_value = dict(payload["update"])
        update_value["messages"] = [ToolMessage.model_validate(message) for message in update_value.get("messages", [])]
        return Command(update=update_value)
    raise ToolLedgerError("账本中的工具结果格式不可识别")


def tool_result_error_code(result: ToolMessage | Command) -> str | None:
    messages: list[ToolMessage]
    if isinstance(result, ToolMessage):
        messages = [result]
    elif isinstance(result, Command) and isinstance(result.update, dict):
        messages = [message for message in result.update.get("messages", []) if isinstance(message, ToolMessage)]
    else:
        return "INVALID_TOOL_RESULT"
    for message in messages:
        # error ToolMessage 也可能携带更具体的业务错误码；先解析正文，
        # 避免把 SKILL_TOOL_DENIED 等原因降级成通用错误。
        if isinstance(message.content, str):
            try:
                content = json.loads(message.content)
            except (json.JSONDecodeError, TypeError):
                content = None
            if isinstance(content, dict) and (content.get("ok") is False or message.status == "error"):
                error = content.get("error") or {}
                if isinstance(error, dict) and error.get("code"):
                    return str(error["code"])
        if message.status == "error":
            return "TOOL_RETURNED_ERROR"
    return None


class ToolLedgerService:
    """用数据库唯一键约束一次逻辑工具调用只对应一条账本记录。"""

    def __init__(self, sessions: async_sessionmaker) -> None:
        self.sessions = sessions

    async def prepare(
        self,
        run_id: str,
        tool_call_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        scope: str = "lead",
        replay_class: ReplayClass | None = None,
        precondition: dict[str, Any] | None = None,
    ) -> ToolExecutionRecord:
        args_json = canonical_json(arguments)
        args_digest = hashlib.sha256(args_json.encode("utf-8")).hexdigest()
        async with self.sessions.begin() as session:
            row = await session.scalar(
                select(ToolExecutionRow).where(
                    ToolExecutionRow.run_id == run_id,
                    ToolExecutionRow.scope == scope,
                    ToolExecutionRow.tool_call_id == tool_call_id,
                )
            )
            if row is None:
                row = ToolExecutionRow(
                    id=str(uuid4()),
                    run_id=run_id,
                    scope=scope,
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    args_hash=args_digest,
                    args_json=args_json,
                    replay_class=replay_class or replay_class_for(tool_name),
                    status="prepared",
                    result_json=None,
                    precondition_json=None if precondition is None else canonical_json(precondition),
                    error_code=None,
                    attempts=0,
                    created_at=_now(),
                    started_at=None,
                    finished_at=None,
                )
                session.add(row)
                await session.flush()
            elif row.tool_name != tool_name or row.args_hash != args_digest or row.args_json != args_json:
                raise ToolCallConflict("同一个 tool_call_id 不能改用其他工具或参数")
            elif precondition is not None:
                expected = canonical_json(precondition)
                if row.precondition_json not in (None, expected):
                    raise ToolCallConflict("同一个 tool_call_id 的执行前置条件发生变化")
                if row.precondition_json is None:
                    row.precondition_json = expected
            return ToolExecutionRecord.from_row(row)

    async def begin(self, record_id: str) -> ToolExecutionRecord:
        now = _now()
        async with self.sessions.begin() as session:
            result = await session.execute(
                update(ToolExecutionRow)
                .where(ToolExecutionRow.id == record_id, ToolExecutionRow.status == "prepared")
                .values(status="running", attempts=ToolExecutionRow.attempts + 1, started_at=now)
            )
            row = await session.get(ToolExecutionRow, record_id)
            if row is None:
                raise ToolLedgerError("工具账本记录不存在")
            if result.rowcount != 1 and row.status != "running":
                raise ToolLedgerError(f"工具账本状态不允许开始执行：{row.status}")
            return ToolExecutionRecord.from_row(row)

    # 记录结果
    async def finish(self, record_id: str, result: ToolMessage | Command) -> ToolExecutionRecord:
        payload = serialize_tool_result(result)
        error_code = tool_result_error_code(result)
        status = "failed" if error_code else "succeeded"
        async with self.sessions.begin() as session:
            await session.execute(
                update(ToolExecutionRow)
                .where(ToolExecutionRow.id == record_id, ToolExecutionRow.status == "running")
                .values(
                    status=status,
                    result_json=canonical_json(payload),
                    error_code=error_code,
                    finished_at=_now(),
                )
            )
            row = await session.get(ToolExecutionRow, record_id, populate_existing=True)
            if row is None:
                raise ToolLedgerError("工具账本记录不存在")
            return ToolExecutionRecord.from_row(row)

    async def fail_exception(self, record_id: str, error: Exception) -> ToolExecutionRecord:
        async with self.sessions.begin() as session:
            row = await session.get(ToolExecutionRow, record_id)
            if row is None:
                raise ToolLedgerError("工具账本记录不存在")
            status = "failed" if row.replay_class == "read_only" else "uncertain"
            row.status = status
            row.error_code = type(error).__name__
            row.finished_at = _now() if status == "failed" else None
            await session.flush()
            return ToolExecutionRecord.from_row(row)

    async def deny(self, record_id: str, *, reason: str) -> ToolExecutionRecord:
        async with self.sessions.begin() as session:
            await session.execute(
                update(ToolExecutionRow)
                .where(ToolExecutionRow.id == record_id, ToolExecutionRow.status == "prepared")
                .values(
                    status="denied",
                    result_json=canonical_json({"reason": reason}),
                    error_code="TOOL_BATCH_REJECTED",
                    finished_at=_now(),
                )
            )
            row = await session.get(ToolExecutionRow, record_id, populate_existing=True)
            if row is None:
                raise ToolLedgerError("工具账本记录不存在")
            return ToolExecutionRecord.from_row(row)

    async def list_for_run(self, run_id: str) -> list[ToolExecutionRecord]:
        async with self.sessions() as session:
            rows = await session.scalars(
                select(ToolExecutionRow)
                .where(ToolExecutionRow.run_id == run_id)
                .order_by(ToolExecutionRow.created_at, ToolExecutionRow.id)
            )
            return [ToolExecutionRecord.from_row(row) for row in rows]

    async def attempt_snapshot(self, run_id: str) -> dict[str, int]:
        """返回逻辑调用到真实开始次数的映射，重放不会增加 attempts。"""
        records = await self.list_for_run(run_id)
        return {record.tool_call_id: record.attempts for record in records}

    async def has_uncertain(self, run_id: str) -> bool:
        async with self.sessions() as session:
            row = await session.scalar(
                select(ToolExecutionRow.id).where(
                    ToolExecutionRow.run_id == run_id,
                    ToolExecutionRow.status == "uncertain",
                )
            )
            return row is not None

    async def resolve_uncertain(
        self,
        record_id: str,
        *,
        action: Literal["skip", "verify"],
        evidence: list[dict[str, str]],
        workspace: "WorkspaceService",
    ) -> ToolExecutionRecord:
        """人工放弃不明结果，或用服务端重新读取的文件 hash 证明它已完成。"""
        async with self.sessions() as session:
            row = await session.get(ToolExecutionRow, record_id)
            if row is None:
                raise ToolExecutionNotFound("工具执行记录不存在")
            if row.status != "uncertain":
                raise ToolResolutionConflict(f"只有 uncertain 工具可以处理，当前为 {row.status}")
            run = await session.get(RunRow, row.run_id)
            if run is None:
                raise ToolExecutionNotFound("工具所属 Run 不存在")
            record = ToolExecutionRecord.from_row(row)

        if action == "verify":
            if not evidence:
                raise ToolEvidenceMismatch("verify 至少需要一项文件路径和预期 SHA-256")
            declared = set()
            if record.precondition:
                declared.update(record.precondition.get("evidence_paths") or [])
                if isinstance(record.precondition.get("path"), str):
                    declared.add(record.precondition["path"])
            facts = []
            for item in evidence:
                path = item.get("path")
                expected = item.get("sha256")
                if not isinstance(path, str) or path not in declared:
                    raise ToolEvidenceMismatch("只能核验工具调用时预先声明的证据路径")
                if not isinstance(expected, str) or len(expected) != 64:
                    raise ToolEvidenceMismatch("证据必须提供 64 位 SHA-256")
                try:
                    actual = await asyncio.to_thread(workspace.inspect_file, run.thread_id, path)
                except Exception as exc:
                    raise ToolEvidenceMismatch(f"证据文件不可读：{path}") from exc
                if actual.sha256 != expected:
                    raise ToolEvidenceMismatch(f"证据 hash 不匹配：{path}")
                facts.append({"path": path, "sha256": actual.sha256, "size_bytes": actual.size_bytes})
            message = ToolMessage(
                content=canonical_json({"ok": True, "recovered": True, "evidence": facts}),
                name=record.tool_name,
                tool_call_id=record.tool_call_id,
            )
            status = "succeeded"
            error_code = None
        else:
            message = ToolMessage(
                content=canonical_json(
                    {
                        "ok": False,
                        "error": {
                            "code": "TOOL_RESULT_ABANDONED",
                            "message": "工具结果不确定，用户已选择放弃且不会自动重放",
                        },
                    }
                ),
                name=record.tool_name,
                tool_call_id=record.tool_call_id,
                status="error",
            )
            status = "failed"
            error_code = "TOOL_RESULT_ABANDONED"

        async with self.sessions.begin() as session:
            result = await session.execute(
                update(ToolExecutionRow)
                .where(ToolExecutionRow.id == record_id, ToolExecutionRow.status == "uncertain")
                .values(
                    status=status,
                    result_json=canonical_json(serialize_tool_result(message)),
                    error_code=error_code,
                    finished_at=_now(),
                )
            )
            if result.rowcount != 1:
                raise ToolResolutionConflict("工具结果已被其他请求处理")
            row = await session.get(ToolExecutionRow, record_id, populate_existing=True)
            assert row is not None
            return ToolExecutionRecord.from_row(row)

    async def cancel_open_for_run(self, run_id: str) -> list[ToolMessage]:
        """取消 Run 时为所有未响应调用写入明确失败结果，供 checkpoint 和 UI 配对。"""
        now = _now()
        messages: list[ToolMessage] = []
        async with self.sessions.begin() as session:
            rows = list(
                await session.scalars(
                    select(ToolExecutionRow).where(
                        ToolExecutionRow.run_id == run_id,
                        ToolExecutionRow.status.in_(("prepared", "running", "uncertain")),
                    )
                )
            )
            for row in rows:
                message = ToolMessage(
                    content=canonical_json(
                        {
                            "ok": False,
                            "error": {
                                "code": "RUN_CANCELLED",
                                "message": "Run 已取消；该工具没有可确认的成功结果",
                            },
                        }
                    ),
                    name=row.tool_name,
                    tool_call_id=row.tool_call_id,
                    status="error",
                )
                row.status = "cancelled"
                row.result_json = canonical_json(serialize_tool_result(message))
                row.error_code = "RUN_CANCELLED"
                row.finished_at = now
                messages.append(message)
        return messages

    async def mark_orphaned_running_uncertain(self) -> set[str]:
        """应用启动时不猜测上次进程中的写操作是否已经完成，直接将其设置为uncertain。"""
        async with self.sessions.begin() as session:
            await session.execute(
                update(ToolExecutionRow)
                .where(ToolExecutionRow.status == "running")
                .values(status="uncertain", error_code="PROCESS_RESTARTED_DURING_TOOL")
            )
            # 若进程恰好在“账本已变 uncertain、Run 尚未变 interrupted”之间再次退出，
            # 下次启动仍要找到这批 Run，不能只返回本次 UPDATE 命中的行。
            return set(
                await session.scalars(select(ToolExecutionRow.run_id).where(ToolExecutionRow.status == "uncertain"))
            )
