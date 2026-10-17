"""把实际文件捕获为不可变快照，再登记到 artifacts 表。"""

import asyncio
import hashlib
import mimetypes
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from agentloom.persistence.models import ArtifactRow, RunRow, ThreadRow
from agentloom.sandbox import PathOutOfScope, WorkspaceService
from agentloom.sandbox.workspace import DEFAULT_MAX_FILE_BYTES, WINDOWS_RESERVED_NAMES

MAX_ARTIFACT_BYTES = DEFAULT_MAX_FILE_BYTES
SAFE_FILENAME = re.compile(r"^[^\x00-\x1f<>:\"/\\|?*]+$")


class ArtifactError(RuntimeError):
    """带稳定错误码的产物服务错误。"""

    code = "ARTIFACT_ERROR"


class ArtifactNotFound(ArtifactError):
    code = "ARTIFACT_NOT_FOUND"


class ArtifactIntegrityError(ArtifactError):
    code = "ARTIFACT_INTEGRITY_FAILED"


class ArtifactOwnershipError(ArtifactError):
    code = "ARTIFACT_OWNERSHIP_MISMATCH"


@dataclass(frozen=True)
class ArtifactRecord:
    id: str
    thread_id: str
    run_id: str | None
    kind: str
    display_name: str
    relative_path: str
    sha256: str
    size_bytes: int
    mime_type: str
    created_at: str

    @classmethod
    def from_row(cls, row: ArtifactRow) -> "ArtifactRecord":
        return cls(
            id=row.id,
            thread_id=row.thread_id,
            run_id=row.run_id,
            kind=row.kind,
            display_name=row.display_name,
            relative_path=row.relative_path,
            sha256=row.sha256,
            size_bytes=row.size_bytes,
            mime_type=row.mime_type,
            created_at=row.created_at,
        )


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _safe_display_name(filename: str) -> str:
    name = Path(filename.replace("\\", "/")).name.strip()
    stem = name.split(".", 1)[0].upper()
    if (
        name in {"", ".", ".."}
        or name.endswith((".", " "))
        or stem in WINDOWS_RESERVED_NAMES
        or not SAFE_FILENAME.fullmatch(name)
    ):
        raise PathOutOfScope("文件名包含不允许的字符")
    return name


def _mime_type(filename: str) -> str:
    return mimetypes.guess_type(filename)[0] or "application/octet-stream"


class ArtifactService:
    """负责 artifacts 短事务，文件读写委托给 WorkspaceService。"""

    def __init__(self, sessions: async_sessionmaker, workspace: WorkspaceService) -> None:
        self.sessions = sessions
        self.workspace = workspace

    async def _require_thread(self, thread_id: str) -> None:
        async with self.sessions() as session:
            if await session.get(ThreadRow, thread_id) is None:
                raise ArtifactNotFound("线程不存在")

    async def register_upload(self, thread_id: str, filename: str, content: bytes) -> ArtifactRecord:
        await self._require_thread(thread_id)
        if len(content) > MAX_ARTIFACT_BYTES:
            raise ArtifactIntegrityError(f"上传超过 {MAX_ARTIFACT_BYTES} 字节限制")
        artifact_id = str(uuid4())
        display_name = _safe_display_name(filename)
        relative_path = f"uploads/{artifact_id}/{display_name}"
        sha256 = hashlib.sha256(content).hexdigest()
        await asyncio.to_thread(self.workspace.store_snapshot, thread_id, relative_path, content)
        row = ArtifactRow(
            id=artifact_id,
            thread_id=thread_id,
            run_id=None,
            subagent_task_id=None,
            kind="upload",
            display_name=display_name,
            relative_path=relative_path,
            sha256=sha256,
            size_bytes=len(content),
            mime_type=_mime_type(display_name),
            created_at=_now(),
        )
        try:
            async with self.sessions.begin() as session:
                session.add(row)
        except Exception:
            await asyncio.to_thread(self.workspace.delete_snapshot, thread_id, relative_path)
            raise
        return ArtifactRecord.from_row(row)

    async def register_outputs(self, thread_id: str, run_id: str, filepaths: list[str]) -> list[ArtifactRecord]:
        filepaths = list(dict.fromkeys(filepaths))
        if not filepaths:
            raise ArtifactIntegrityError("至少需要一个输出文件")
        if len(filepaths) > 20:
            raise ArtifactIntegrityError("一次最多登记 20 个输出文件")
        async with self.sessions() as session:
            run = await session.get(RunRow, run_id)
            if run is None or run.thread_id != thread_id or run.status != "running":
                raise ArtifactOwnershipError("Run 不属于当前线程或当前不在执行中")

        sources = []
        total_size = 0
        for filepath in filepaths:
            source = await asyncio.to_thread(self.workspace.read_output_snapshot_source, thread_id, filepath)
            total_size += source.size_bytes
            if total_size > MAX_ARTIFACT_BYTES:
                raise ArtifactIntegrityError(f"本批产物超过 {MAX_ARTIFACT_BYTES} 字节限制")
            sources.append(source)

        records: list[tuple[ArtifactRow, str]] = []
        try:
            for source in sources:
                artifact_id = str(uuid4())
                display_name = _safe_display_name(source.name)
                relative_path = f"artifacts/{artifact_id}/{display_name}"
                await asyncio.to_thread(
                    self.workspace.store_snapshot,
                    thread_id,
                    relative_path,
                    source.content,
                )
                records.append(
                    (
                        ArtifactRow(
                            id=artifact_id,
                            thread_id=thread_id,
                            run_id=run_id,
                            subagent_task_id=None,
                            kind="output",
                            display_name=display_name,
                            relative_path=relative_path,
                            sha256=source.sha256,
                            size_bytes=source.size_bytes,
                            mime_type=_mime_type(display_name),
                            created_at=_now(),
                        ),
                        relative_path,
                    )
                )
            async with self.sessions.begin() as session:
                session.add_all(row for row, _ in records)
        except Exception:
            for _, relative_path in records:
                await asyncio.to_thread(self.workspace.delete_snapshot, thread_id, relative_path)
            raise
        return [ArtifactRecord.from_row(row) for row, _ in records]

    async def get(self, artifact_id: str, *, thread_id: str | None = None) -> ArtifactRecord:
        async with self.sessions() as session:
            statement = select(ArtifactRow).where(ArtifactRow.id == artifact_id)
            if thread_id is not None:
                statement = statement.where(ArtifactRow.thread_id == thread_id)
            row = await session.scalar(statement)
        if row is None:
            raise ArtifactNotFound("产物不存在或不属于当前线程")
        return ArtifactRecord.from_row(row)

    async def list_for_thread(self, thread_id: str) -> list[ArtifactRecord]:
        """按创建时间返回线程的上传和不可变输出快照。"""
        await self._require_thread(thread_id)
        async with self.sessions() as session:
            rows = await session.scalars(
                select(ArtifactRow)
                .where(ArtifactRow.thread_id == thread_id)
                .order_by(ArtifactRow.created_at.desc(), ArtifactRow.id)
            )
            return [ArtifactRecord.from_row(row) for row in rows]

    async def read_content(self, artifact_id: str, *, thread_id: str | None = None) -> tuple[ArtifactRecord, bytes]:
        record = await self.get(artifact_id, thread_id=thread_id)
        try:
            content = await asyncio.to_thread(
                self.workspace.read_snapshot,
                record.thread_id,
                record.relative_path,
            )
        except Exception as exc:
            raise ArtifactIntegrityError("产物快照缺失或不可读") from exc
        if len(content) != record.size_bytes or hashlib.sha256(content).hexdigest() != record.sha256:
            raise ArtifactIntegrityError("产物快照与登记的大小或 SHA-256 不一致")
        return record, content
