"""Coder 变更的 diff、审批、Docker 验证和原子接纳。"""

import asyncio
import difflib
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from agentloom.persistence.events import append_run_event
from agentloom.persistence.models import ApprovalRow, CoderChangeProposalRow, RunRow, SubagentTaskRow
from agentloom.runtime.approvals import ApprovalRecord
from agentloom.runtime.ledger import canonical_json
from agentloom.sandbox import FileContentMismatch, WorkspaceService
from agentloom.sandbox.workspace import WorkspaceFileNotFound

MAX_CHANGE_FILES = 100
MAX_CHANGE_BYTES = 10 * 1024 * 1024
MAX_DIFF_CHARS = 300_000


class CoderChangeError(RuntimeError):
    code = "CODER_CHANGE_ERROR"


class CoderChangeNotFound(CoderChangeError):
    code = "CODER_CHANGE_NOT_FOUND"


class CoderChangeConflict(CoderChangeError):
    code = "CODER_CHANGE_CONFLICT"


class CoderVerificationFailed(CoderChangeError):
    code = "CODER_VERIFICATION_FAILED"


@dataclass(frozen=True)
class CoderChangeRecord:
    id: str
    task_id: str
    run_id: str
    thread_id: str
    approval_id: str
    status: str
    manifest_hash: str
    manifest: dict[str, Any]
    verification: dict[str, Any] | None
    error_code: str | None
    error_message: str | None
    created_at: str
    resolved_at: str | None

    @classmethod
    def from_row(cls, row: CoderChangeProposalRow) -> "CoderChangeRecord":
        return cls(
            row.id,
            row.task_id,
            row.run_id,
            row.thread_id,
            row.approval_id,
            row.status,
            row.manifest_hash,
            json.loads(row.manifest_json),
            None if row.verification_json is None else json.loads(row.verification_json),
            row.error_code,
            row.error_message,
            row.created_at,
            row.resolved_at,
        )


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class CoderChangeService:
    """可信服务端生成提案；客户端只能批准冻结的 manifest。"""

    def __init__(
        self, sessions: async_sessionmaker, workspace: WorkspaceService, docker, *, event_notifier=None
    ) -> None:
        self.sessions = sessions
        self.workspace = workspace
        self.docker = docker
        self.event_notifier = event_notifier
        self._proposal_lock = asyncio.Lock()
        self._accept_lock = asyncio.Lock()

    def _notify(self, run_id: str) -> None:
        if self.event_notifier is not None:
            self.event_notifier(run_id)

    @staticmethod
    def _stable_file(path: Path) -> bytes:
        if not path.is_file() or path.is_symlink():
            raise CoderChangeConflict(f"Coder 文件不是普通文件：{path.name}")
        before = path.stat()
        content = path.read_bytes()
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise CoderChangeConflict(f"读取期间 Coder 文件发生变化：{path.name}")
        return content

    def _build_manifest(self, thread_id: str, task_id: str, command: str) -> dict[str, Any]:
        try:
            task_key = str(UUID(task_id))
        except ValueError as exc:
            raise CoderChangeConflict("Coder 子任务 ID 无效") from exc
        thread_root = self.workspace.thread_root(thread_id)
        task_root = thread_root / "tasks" / task_key / "workspace"
        self.workspace._reject_link_components(thread_root, task_root)
        task_root.mkdir(parents=True, exist_ok=True)
        self.workspace._reject_link_components(thread_root, task_root)
        task_root = task_root.resolve(strict=True)
        files = [path for path in sorted(task_root.rglob("*")) if path.is_file()]
        if not files:
            raise CoderChangeConflict("Coder 没有生成可接纳文件")
        if len(files) > MAX_CHANGE_FILES:
            raise CoderChangeConflict(f"Coder 变更超过 {MAX_CHANGE_FILES} 个文件")
        items, total = [], 0
        for source in files:
            self.workspace._reject_link_components(task_root, source)
            if self.workspace._is_link_or_junction(source):
                raise CoderChangeConflict("Coder 变更不能包含链接")
            try:
                relative = source.resolve().relative_to(task_root).as_posix()
            except ValueError as exc:
                raise CoderChangeConflict("Coder 文件越出私有工作区") from exc
            proposed = self._stable_file(source)
            total += len(proposed)
            if total > MAX_CHANGE_BYTES:
                raise CoderChangeConflict("Coder 变更总大小超过 10 MiB")
            try:
                proposed_text = proposed.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise CoderChangeConflict(f"首版只接纳 UTF-8 文本：{relative}") from exc
            parent_path = f"/mnt/user-data/workspace/{relative}"
            try:
                parent = self.workspace.inspect_file(thread_id, parent_path)
                base_content, base_hash, operation = parent.content, parent.sha256, "modify"
            except WorkspaceFileNotFound:
                base_content, base_hash, operation = b"", None, "create"
            if proposed == base_content:
                continue
            try:
                base_text = base_content.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise CoderChangeConflict(f"父文件不是 UTF-8 文本：{relative}") from exc
            diff = "".join(
                difflib.unified_diff(
                    base_text.splitlines(keepends=True),
                    proposed_text.splitlines(keepends=True),
                    fromfile=f"a/{relative}",
                    tofile=f"b/{relative}",
                )
            )
            items.append(
                {
                    "path": parent_path,
                    "operation": operation,
                    "base_sha256": base_hash,
                    "proposed_sha256": _sha(proposed),
                    "size_bytes": len(proposed),
                    "diff": diff[:MAX_DIFF_CHARS],
                    "diff_truncated": len(diff) > MAX_DIFF_CHARS,
                }
            )
        if not items:
            raise CoderChangeConflict("Coder 文件与父工作区完全相同")
        return {"version": 1, "task_id": task_id, "files": items, "verification_command": command}

    async def create(
        self, task_id: str, *, verification_command: str | None = None
    ) -> tuple[CoderChangeRecord, ApprovalRecord]:
        # 同一任务的并发提交只能生成一份相同 manifest 的审批。
        async with self._proposal_lock:
            return await self._create(task_id, verification_command=verification_command)

    async def _create(
        self, task_id: str, *, verification_command: str | None = None
    ) -> tuple[CoderChangeRecord, ApprovalRecord]:
        async with self.sessions() as session:
            task = await session.get(SubagentTaskRow, task_id)
            if task is None:
                raise CoderChangeNotFound("Coder 子任务不存在")
            run = await session.get(RunRow, task.run_id)
            if run is None or task.agent_type != "coder" or task.status != "succeeded":
                raise CoderChangeConflict("只有已成功的 Coder 子任务可以提交变更")
            result = {} if task.result_json is None else json.loads(task.result_json)
            action = result.get("requires_parent_action") or {}
            command = verification_command or (action.get("command") if action.get("tool") == "bash" else None)
            if not isinstance(command, str) or not command.strip():
                raise CoderChangeConflict("变更提案必须包含 Docker 验证命令")
            thread_id, run_id = run.thread_id, run.id
        manifest = await asyncio.to_thread(self._build_manifest, thread_id, task_id, command.strip())
        manifest_json = canonical_json(manifest)
        manifest_hash = hashlib.sha256(manifest_json.encode()).hexdigest()
        now, proposal_id, approval_id = _now(), str(uuid4()), str(uuid4())
        payload = {
            "version": 1,
            "kind": "coder_change",
            "proposal_id": proposal_id,
            "manifest_hash": manifest_hash,
            **manifest,
        }
        scope = f"coder:{task_id}"
        payload_hash = hashlib.sha256(
            canonical_json({"run_id": run_id, "scope": scope, "payload": payload}).encode()
        ).hexdigest()
        async with self.sessions.begin() as session:
            existing = await session.scalar(
                select(CoderChangeProposalRow).where(
                    CoderChangeProposalRow.task_id == task_id,
                    CoderChangeProposalRow.manifest_hash == manifest_hash,
                )
            )
            if existing is not None:
                approval = await session.get(ApprovalRow, existing.approval_id)
                assert approval is not None
                return CoderChangeRecord.from_row(existing), ApprovalRecord.from_row(approval)
            approval = ApprovalRow(
                id=approval_id,
                run_id=run_id,
                suspend_key=f"coder-change:{manifest_hash}",
                kind="coder_change",
                payload_hash=payload_hash,
                payload_json=canonical_json(payload),
                checkpoint_id=f"coder-change:{proposal_id}",
                status="pending",
                response_json=None,
                created_at=now,
                resolved_at=None,
                consumed_at=None,
            )
            proposal = CoderChangeProposalRow(
                id=proposal_id,
                task_id=task_id,
                run_id=run_id,
                thread_id=thread_id,
                approval_id=approval_id,
                status="pending",
                manifest_hash=manifest_hash,
                manifest_json=manifest_json,
                verification_json=None,
                error_code=None,
                error_message=None,
                created_at=now,
                resolved_at=None,
            )
            session.add_all([approval, proposal])
            await append_run_event(
                session,
                run_id=run_id,
                event_type="approval.required",
                scope=scope,
                payload_json=canonical_json(
                    {
                        "approval_id": approval_id,
                        "kind": "coder_change",
                        "payload_hash": payload_hash,
                        "payload": payload,
                    }
                ),
                created_at=now,
            )
            await session.flush()
        self._notify(run_id)
        return CoderChangeRecord.from_row(proposal), ApprovalRecord.from_row(approval)

    async def get_by_approval(self, approval_id: str) -> CoderChangeRecord:
        async with self.sessions() as session:
            row = await session.scalar(
                select(CoderChangeProposalRow).where(CoderChangeProposalRow.approval_id == approval_id)
            )
        if row is None:
            raise CoderChangeNotFound("变更提案不存在")
        return CoderChangeRecord.from_row(row)

    async def resolve(self, approval: ApprovalRecord) -> CoderChangeRecord:
        record = await self.get_by_approval(approval.id)
        if record.status != "pending":
            return record
        decision = (approval.response or {}).get("decision")
        if decision == "reject":
            async with self.sessions.begin() as session:
                await session.execute(
                    update(CoderChangeProposalRow)
                    .where(CoderChangeProposalRow.id == record.id, CoderChangeProposalRow.status == "pending")
                    .values(status="rejected", resolved_at=_now())
                )
                await append_run_event(
                    session,
                    run_id=record.run_id,
                    event_type="coder_change.finished",
                    scope=f"subagent:{record.task_id}",
                    payload_json=canonical_json({"proposal_id": record.id, "status": "rejected"}),
                    created_at=_now(),
                )
            self._notify(record.run_id)
            return await self.get_by_approval(approval.id)
        if decision != "approve":
            raise CoderChangeConflict("变更审批尚未批准")

        async with self._accept_lock:
            # 两个相同批准请求可能同时到达；取得锁后必须重新读终态。
            record = await self.get_by_approval(approval.id)
            if record.status != "pending":
                return record
            async with self.sessions.begin() as session:
                active = await session.scalar(
                    select(RunRow.id)
                    .where(
                        RunRow.thread_id == record.thread_id,
                        RunRow.status.in_(("pending", "running", "waiting_input", "interrupted", "cancelling")),
                    )
                    .limit(1)
                )
                if active is not None:
                    raise CoderChangeConflict("父线程存在未结束 Run，不能接纳 Coder 变更")
                await session.execute(
                    update(CoderChangeProposalRow)
                    .where(CoderChangeProposalRow.id == record.id, CoderChangeProposalRow.status == "pending")
                    .values(status="verifying")
                )
            try:
                manifest = record.manifest
                result = await self.docker.execute_task(
                    parent_thread_id=record.thread_id,
                    task_id=record.task_id,
                    run_id=record.run_id,
                    command=manifest["verification_command"],
                )
                evidence = {
                    "command": manifest["verification_command"],
                    "exit_code": result.exit_code,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "truncated": result.truncated,
                }
                if result.exit_code != 0:
                    raise CoderVerificationFailed(f"Docker 验证退出码为 {result.exit_code}")
                task_root = self.workspace.thread_root(record.thread_id) / "tasks" / record.task_id / "workspace"
                changes = []
                for item in manifest["files"]:
                    relative = item["path"].removeprefix("/mnt/user-data/workspace/")
                    content = await asyncio.to_thread(self._stable_file, task_root / Path(relative))
                    if _sha(content) != item["proposed_sha256"]:
                        raise CoderChangeConflict(f"Docker 验证后 Coder 文件发生变化：{item['path']}")
                    changes.append({"path": item["path"], "base_sha256": item["base_sha256"], "content": content})
                await asyncio.to_thread(self.workspace.apply_file_set, record.thread_id, changes)
            except Exception as exc:
                status = "conflict" if isinstance(exc, CoderChangeConflict | FileContentMismatch) else "failed"
                async with self.sessions.begin() as session:
                    await session.execute(
                        update(CoderChangeProposalRow)
                        .where(CoderChangeProposalRow.id == record.id)
                        .values(
                            status=status,
                            verification_json=canonical_json(locals().get("evidence", {})),
                            error_code=getattr(exc, "code", type(exc).__name__),
                            error_message=str(exc),
                            resolved_at=_now(),
                        )
                    )
                    await append_run_event(
                        session,
                        run_id=record.run_id,
                        event_type="coder_change.finished",
                        scope=f"subagent:{record.task_id}",
                        payload_json=canonical_json(
                            {
                                "proposal_id": record.id,
                                "status": status,
                                "error_code": getattr(exc, "code", type(exc).__name__),
                            }
                        ),
                        created_at=_now(),
                    )
                self._notify(record.run_id)
                return await self.get_by_approval(approval.id)

            async with self.sessions.begin() as session:
                await session.execute(
                    update(CoderChangeProposalRow)
                    .where(CoderChangeProposalRow.id == record.id, CoderChangeProposalRow.status == "verifying")
                    .values(status="accepted", verification_json=canonical_json(evidence), resolved_at=_now())
                )
                task = await session.get(SubagentTaskRow, record.task_id)
                if task is not None:
                    task.acceptance_json = canonical_json(
                        {"tests_passed": True, "docker": evidence, "manifest_hash": record.manifest_hash}
                    )
                await append_run_event(
                    session,
                    run_id=record.run_id,
                    event_type="coder_change.accepted",
                    scope=f"subagent:{record.task_id}",
                    payload_json=canonical_json(
                        {
                            "proposal_id": record.id,
                            "manifest_hash": record.manifest_hash,
                            "files": [item["path"] for item in record.manifest["files"]],
                        }
                    ),
                    created_at=_now(),
                )
            self._notify(record.run_id)
            return await self.get_by_approval(approval.id)
