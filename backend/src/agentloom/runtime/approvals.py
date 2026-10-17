"""持久化工具批次审批，并把批准绑定到原参数和文件旧 hash。"""

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from agentloom.persistence.events import append_run_event
from agentloom.persistence.models import ApprovalRow, RunRow
from agentloom.runtime.ledger import ToolExecutionRecord, ToolLedgerService, canonical_json, replay_class_for
from agentloom.sandbox import WorkspaceError, WorkspaceService

POLICY_VERSION = "m2.5-v1"
Decision = Literal["approve", "reject"]


class ApprovalError(RuntimeError):
    """带稳定错误码的审批错误。"""

    code = "APPROVAL_ERROR"


class ApprovalNotFound(ApprovalError):
    code = "APPROVAL_NOT_FOUND"


class ApprovalConflict(ApprovalError):
    code = "APPROVAL_CONFLICT"


class ApprovalNotReady(ApprovalError):
    code = "APPROVAL_NOT_READY"


class ApprovalRequired(ApprovalError):
    code = "APPROVAL_REQUIRED"


class ApprovalPreconditionFailed(ApprovalError):
    code = "APPROVAL_PRECONDITION_FAILED"


@dataclass(frozen=True)
class ApprovalRecord:
    id: str
    run_id: str
    suspend_key: str
    kind: str
    payload_hash: str
    payload: dict[str, Any]
    checkpoint_id: str | None
    status: str
    response: dict[str, Any] | None
    created_at: str
    resolved_at: str | None
    consumed_at: str | None

    @classmethod
    def from_row(cls, row: ApprovalRow) -> "ApprovalRecord":
        return cls(
            id=row.id,
            run_id=row.run_id,
            suspend_key=row.suspend_key,
            kind=row.kind,
            payload_hash=row.payload_hash,
            payload=json.loads(row.payload_json),
            checkpoint_id=row.checkpoint_id,
            status=row.status,
            response=None if row.response_json is None else json.loads(row.response_json),
            created_at=row.created_at,
            resolved_at=row.resolved_at,
            consumed_at=row.consumed_at,
        )


@dataclass(frozen=True)
class PreparedApproval:
    approval: ApprovalRecord
    executions: tuple[ToolExecutionRecord, ...]


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _payload_hash(run_id: str, scope: str, payload: dict[str, Any]) -> str:
    bound = {"run_id": run_id, "scope": scope, "payload": payload}
    return hashlib.sha256(canonical_json(bound).encode("utf-8")).hexdigest()


class ApprovalService:
    """准备、答复并消费审批；客户端永远不能直接构造 graph resume。"""

    def __init__(
        self,
        sessions: async_sessionmaker,
        workspace: WorkspaceService,
        ledger: ToolLedgerService,
        *,
        event_notifier: Callable[[str], None] | None = None,
    ) -> None:
        self.sessions = sessions
        self.workspace = workspace
        self.ledger = ledger
        self.event_notifier = event_notifier

    def _notify(self, run_id: str) -> None:
        if self.event_notifier is not None:
            self.event_notifier(run_id)

    async def prepare_tool_batch(
        self,
        thread_id: str,
        run_id: str,
        tool_calls: list[dict[str, Any]],
        *,
        scope: str = "lead",
    ) -> PreparedApproval:
        """在 interrupt 前完成可重入准备，不执行任何工具副作用。"""
        proposal_calls: list[dict[str, Any]] = []
        for call in tool_calls:
            tool_call_id = str(call.get("id") or "")
            tool_name = str(call.get("name") or "")
            arguments = call.get("args")
            if not tool_call_id or not tool_name or not isinstance(arguments, dict):
                raise ApprovalConflict("工具批次缺少稳定调用 ID、名称或结构化参数")
            proposal_calls.append({"tool_call_id": tool_call_id, "tool_name": tool_name, "args": arguments})
        proposal_identity = {
            "run_id": run_id,
            "scope": scope,
            "policy_version": POLICY_VERSION,
            "calls": proposal_calls,
        }
        proposal_digest = hashlib.sha256(canonical_json(proposal_identity).encode("utf-8")).hexdigest()
        suspend_key = f"tool-batch:{proposal_digest}"

        # interrupt 恢复会从节点开头重入。已有审批必须复用首次冻结的旧 hash，
        # 不能在这里重新读取文件并悄悄生成另一份批准对象。
        async with self.sessions() as session:
            existing = await session.scalar(
                select(ApprovalRow).where(ApprovalRow.run_id == run_id, ApprovalRow.suspend_key == suspend_key)
            )
        if existing is not None:
            record = ApprovalRecord.from_row(existing)
            executions = []
            for action in record.payload.get("actions", []):
                executions.append(
                    await self.ledger.prepare(
                        run_id,
                        str(action["tool_call_id"]),
                        str(action["tool_name"]),
                        action["args"],
                        scope=scope,
                        replay_class=replay_class_for(str(action["tool_name"])),
                        precondition=action.get("precondition"),
                    )
                )
            return PreparedApproval(record, tuple(executions))

        actions: list[dict[str, Any]] = []
        executions: list[ToolExecutionRecord] = []
        has_protected_action = False
        for call in tool_calls:
            tool_call_id = str(call.get("id") or "")
            tool_name = str(call.get("name") or "")
            arguments = call.get("args")
            if not tool_call_id or not tool_name or not isinstance(arguments, dict):
                raise ApprovalConflict("工具批次缺少稳定调用 ID、名称或结构化参数")
            precondition: dict[str, Any] | None = None
            requires_approval = tool_name in {"replace_file", "bash", "remember_preference"}
            if tool_name == "replace_file":
                has_protected_action = True
                path = arguments.get("path")
                expected = arguments.get("expected_sha256")
                if not isinstance(path, str) or not isinstance(expected, str):
                    raise ApprovalPreconditionFailed("replace_file 必须提供 path 和 expected_sha256")
                try:
                    current = self.workspace.read_text(thread_id, path)
                except WorkspaceError as exc:
                    raise ApprovalPreconditionFailed(str(exc)) from exc
                if current.sha256 != expected:
                    raise ApprovalPreconditionFailed("提案中的 expected_sha256 与当前文件不一致")
                precondition = {"path": path, "old_sha256": current.sha256}
            elif tool_name == "bash":
                has_protected_action = True
                if not isinstance(arguments.get("command"), str) or not arguments["command"].strip():
                    raise ApprovalPreconditionFailed("bash 必须提供非空 command")
                evidence_paths = arguments.get("evidence_paths")
                if not isinstance(evidence_paths, list) or len(evidence_paths) > 20:
                    raise ApprovalPreconditionFailed("bash evidence_paths 必须是至多 20 项的列表")
                for path in evidence_paths:
                    if not isinstance(path, str):
                        raise ApprovalPreconditionFailed("bash 证据路径必须是字符串")
                    try:
                        self.workspace.validate_evidence_path(path)
                    except WorkspaceError as exc:
                        raise ApprovalPreconditionFailed(str(exc)) from exc
                precondition = {"evidence_paths": evidence_paths}
            elif tool_name == "remember_preference":
                has_protected_action = True
                memory_key = arguments.get("memory_key")
                content = arguments.get("content")
                expected_version = arguments.get("expected_version", 0)
                if not isinstance(memory_key, str) or not memory_key:
                    raise ApprovalPreconditionFailed("remember_preference 必须提供 memory_key")
                if not isinstance(content, str) or not content.strip():
                    raise ApprovalPreconditionFailed("remember_preference 必须提供非空 content")
                if not isinstance(expected_version, int) or isinstance(expected_version, bool) or expected_version < 0:
                    raise ApprovalPreconditionFailed("remember_preference 的 expected_version 必须是非负整数")
                precondition = {"expected_version": expected_version}
            execution = await self.ledger.prepare(
                run_id,
                tool_call_id,
                tool_name,
                arguments,
                scope=scope,
                replay_class=replay_class_for(tool_name),
                precondition=precondition,
            )
            executions.append(execution)
            actions.append(
                {
                    "tool_call_id": tool_call_id,
                    "tool_name": tool_name,
                    "args": arguments,
                    "requires_approval": requires_approval,
                    "precondition": precondition,
                }
            )
        if not has_protected_action:
            raise ApprovalConflict("工具批次中没有需要审批的动作")

        payload = {
            "version": 1,
            "kind": "tool_batch",
            "policy_version": POLICY_VERSION,
            "actions": actions,
        }
        digest = _payload_hash(run_id, scope, payload)
        async with self.sessions.begin() as session:
            row = await session.scalar(
                select(ApprovalRow).where(ApprovalRow.run_id == run_id, ApprovalRow.suspend_key == suspend_key)
            )
            if row is None:
                row = ApprovalRow(
                    id=str(uuid4()),
                    run_id=run_id,
                    suspend_key=suspend_key,
                    kind="tool_batch",
                    payload_hash=digest,
                    payload_json=canonical_json(payload),
                    checkpoint_id=None,
                    status="pending",
                    response_json=None,
                    created_at=_now(),
                    resolved_at=None,
                    consumed_at=None,
                )
                session.add(row)
                await session.flush()
            elif row.payload_hash != digest or row.payload_json != canonical_json(payload):
                raise ApprovalConflict("相同暂停键对应的审批载荷发生变化")
            return PreparedApproval(ApprovalRecord.from_row(row), tuple(executions))

    async def get(self, approval_id: str) -> ApprovalRecord:
        async with self.sessions() as session:
            row = await session.get(ApprovalRow, approval_id)
        if row is None:
            raise ApprovalNotFound("审批不存在")
        return ApprovalRecord.from_row(row)

    async def list_for_run(self, run_id: str) -> list[ApprovalRecord]:
        async with self.sessions() as session:
            rows = await session.scalars(
                select(ApprovalRow).where(ApprovalRow.run_id == run_id).order_by(ApprovalRow.created_at)
            )
            return [ApprovalRecord.from_row(row) for row in rows]

    async def pending_for_run(self, run_id: str) -> ApprovalRecord | None:
        async with self.sessions() as session:
            row = await session.scalar(
                select(ApprovalRow)
                .where(ApprovalRow.run_id == run_id, ApprovalRow.status == "pending")
                .order_by(ApprovalRow.created_at.desc())
            )
            return None if row is None else ApprovalRecord.from_row(row)

    async def expire_pending_for_run(self, run_id: str) -> int:
        """取消 Run 时关闭审批入口，避免终态 Run 又被恢复。"""
        async with self.sessions.begin() as session:
            result = await session.execute(
                update(ApprovalRow)
                .where(ApprovalRow.run_id == run_id, ApprovalRow.status == "pending")
                .values(status="expired", resolved_at=_now())
            )
            return int(result.rowcount or 0)

    async def resolve(
        self,
        approval_id: str,
        *,
        payload_hash: str,
        decision: Decision,
        reason: str | None,
    ) -> tuple[ApprovalRecord, bool]:
        response = {"decision": decision, "reason": reason}
        response_json = canonical_json(response)
        now = _now()
        newly_resolved = False
        async with self.sessions.begin() as session:
            row = await session.get(ApprovalRow, approval_id)
            if row is None:
                raise ApprovalNotFound("审批不存在")
            if row.payload_hash != payload_hash:
                raise ApprovalConflict("审批载荷 hash 不匹配，不能批准被替换的参数")
            if row.checkpoint_id is None:
                raise ApprovalNotReady("对应 interrupt 尚未持久化，当前不能答复")
            if row.status == "pending":
                result = await session.execute(
                    update(ApprovalRow)
                    .where(ApprovalRow.id == approval_id, ApprovalRow.status == "pending")
                    .values(
                        status="approved" if decision == "approve" else "rejected",
                        response_json=response_json,
                        resolved_at=now,
                    )
                )
                newly_resolved = result.rowcount == 1
                row = await session.get(ApprovalRow, approval_id, populate_existing=True)
                assert row is not None
            if row.response_json != response_json:
                raise ApprovalConflict("审批已经用不同答复解决")
            if newly_resolved:
                run = await session.get(RunRow, row.run_id)
                if run is None:
                    raise ApprovalConflict("审批所属 Run 不存在")
                await append_run_event(
                    session,
                    run_id=run.id,
                    event_type="approval.resolved",
                    scope="lead",
                    payload_json=canonical_json({"approval_id": row.id, "status": row.status, "decision": decision}),
                    created_at=now,
                )
            record = ApprovalRecord.from_row(row)
        if newly_resolved:
            self._notify(record.run_id)
        return record, newly_resolved

    async def consume_response(self, approval_id: str, payload_hash: str) -> ApprovalRecord:
        async with self.sessions.begin() as session:
            row = await session.get(ApprovalRow, approval_id)
            if row is None:
                raise ApprovalNotFound("审批不存在")
            if row.payload_hash != payload_hash or row.status not in {"approved", "rejected"}:
                raise ApprovalConflict("恢复答复与持久化审批不一致")
            if row.consumed_at is None:
                row.consumed_at = _now()
                await session.flush()
            return ApprovalRecord.from_row(row)

    async def authorize_replace(
        self,
        *,
        thread_id: str,
        run_id: str,
        tool_call_id: str,
        arguments: dict[str, Any],
    ) -> ApprovalRecord:
        """工具执行点再次校验批准对象，防止绕过中间件或复用旧批准。"""
        async with self.sessions() as session:
            rows = await session.scalars(
                select(ApprovalRow).where(
                    ApprovalRow.run_id == run_id,
                    ApprovalRow.kind == "tool_batch",
                    ApprovalRow.status == "approved",
                )
            )
            candidates = list(rows)
        matched: ApprovalRecord | None = None
        precondition: dict[str, Any] | None = None
        for row in candidates:
            record = ApprovalRecord.from_row(row)
            for action in record.payload.get("actions", []):
                if (
                    action.get("tool_call_id") == tool_call_id
                    and action.get("tool_name") == "replace_file"
                    and canonical_json(action.get("args")) == canonical_json(arguments)
                ):
                    matched = record
                    precondition = action.get("precondition")
                    break
            if matched is not None:
                break
        if matched is None:
            raise ApprovalRequired("replace_file 没有匹配的服务端批准记录")
        if not isinstance(precondition, dict):
            raise ApprovalPreconditionFailed("批准记录缺少文件旧 hash")
        current = self.workspace.read_text(thread_id, str(arguments.get("path")))
        if current.sha256 != precondition.get("old_sha256"):
            raise ApprovalPreconditionFailed("文件在批准后发生变化，旧审批已失效，请重新提案")
        return matched

    async def authorize_bash(
        self,
        *,
        run_id: str,
        tool_call_id: str,
        arguments: dict[str, Any],
    ) -> ApprovalRecord:
        """执行点按 tool_call_id 和完整参数复核 Bash 批准记录。"""
        async with self.sessions() as session:
            rows = await session.scalars(
                select(ApprovalRow).where(
                    ApprovalRow.run_id == run_id,
                    ApprovalRow.kind == "tool_batch",
                    ApprovalRow.status == "approved",
                )
            )
            candidates = list(rows)
        for row in candidates:
            record = ApprovalRecord.from_row(row)
            for action in record.payload.get("actions", []):
                if (
                    action.get("tool_call_id") == tool_call_id
                    and action.get("tool_name") == "bash"
                    and canonical_json(action.get("args")) == canonical_json(arguments)
                ):
                    return record
        raise ApprovalRequired("bash 没有匹配的服务端批准记录")

    async def authorize_preference(
        self,
        *,
        run_id: str,
        tool_call_id: str,
        arguments: dict[str, Any],
    ) -> ApprovalRecord:
        """执行点再次确认用户批准的是同一条偏好及版本。"""
        normalized_arguments = dict(arguments)
        normalized_arguments.setdefault("expected_version", 0)
        async with self.sessions() as session:
            rows = await session.scalars(
                select(ApprovalRow).where(
                    ApprovalRow.run_id == run_id,
                    ApprovalRow.kind == "tool_batch",
                    ApprovalRow.status == "approved",
                )
            )
            candidates = list(rows)
        for row in candidates:
            record = ApprovalRecord.from_row(row)
            for action in record.payload.get("actions", []):
                approved_arguments = dict(action.get("args") or {})
                approved_arguments.setdefault("expected_version", 0)
                if (
                    action.get("tool_call_id") == tool_call_id
                    and action.get("tool_name") == "remember_preference"
                    and canonical_json(approved_arguments) == canonical_json(normalized_arguments)
                ):
                    return record
        raise ApprovalRequired("remember_preference 没有匹配的服务端批准记录")
