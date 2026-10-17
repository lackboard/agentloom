"""app.sqlite 中少量、显式确认的偏好记忆仓储。"""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from agentloom.persistence.models import MemoryRow


def _now() -> str:
    return datetime.now(UTC).isoformat()


class MemoryError(RuntimeError):
    code = "MEMORY_ERROR"


class MemoryNotFound(MemoryError):
    code = "MEMORY_NOT_FOUND"


class MemoryConflict(MemoryError):
    code = "MEMORY_VERSION_CONFLICT"


@dataclass(frozen=True)
class MemoryRecord:
    id: str
    scope_key: str
    category: str
    memory_key: str
    content: str
    status: str
    source_run_id: str | None
    version: int
    created_at: str
    updated_at: str
    expires_at: str | None

    @classmethod
    def from_row(cls, row: MemoryRow) -> "MemoryRecord":
        return cls(
            id=row.id,
            scope_key=row.scope_key,
            category=row.category,
            memory_key=row.memory_key,
            content=row.content,
            status=row.status,
            source_run_id=row.source_run_id,
            version=row.version,
            created_at=row.created_at,
            updated_at=row.updated_at,
            expires_at=row.expires_at,
        )


class MemoryService:
    """只让 active 且未过期的确认记录进入模型上下文。"""

    def __init__(self, sessions: async_sessionmaker, *, scope_key: str = "local") -> None:
        self.sessions = sessions
        self.scope_key = scope_key

    async def list_active(self) -> list[MemoryRecord]:
        now = _now()
        async with self.sessions() as session:
            rows = await session.scalars(
                select(MemoryRow)
                .where(
                    MemoryRow.scope_key == self.scope_key,
                    MemoryRow.status == "active",
                    or_(MemoryRow.expires_at.is_(None), MemoryRow.expires_at > now),
                )
                .order_by(MemoryRow.updated_at, MemoryRow.id)
            )
            return [MemoryRecord.from_row(row) for row in rows]

    async def create_active(
        self,
        *,
        category: str,
        memory_key: str,
        content: str,
        source_run_id: str | None = None,
        expires_at: str | None = None,
    ) -> MemoryRecord:
        """用户通过 API 明确保存；同键 active 记录必须走带版本的更新。"""
        now = _now()
        try:
            async with self.sessions.begin() as session:
                existing = await session.scalar(
                    select(MemoryRow).where(
                        MemoryRow.scope_key == self.scope_key,
                        MemoryRow.category == category,
                        MemoryRow.memory_key == memory_key,
                    )
                )
                if existing is not None:
                    if existing.status != "deleted":
                        raise MemoryConflict("相同 memory_key 已存在，请使用当前 version 更新")
                    existing.content = content
                    existing.status = "active"
                    existing.source_run_id = source_run_id
                    existing.version += 1
                    existing.updated_at = now
                    existing.expires_at = expires_at
                    await session.flush()
                    return MemoryRecord.from_row(existing)
                row = MemoryRow(
                    id=str(uuid4()),
                    scope_key=self.scope_key,
                    category=category,
                    memory_key=memory_key,
                    content=content,
                    status="active",
                    source_run_id=source_run_id,
                    version=1,
                    created_at=now,
                    updated_at=now,
                    expires_at=expires_at,
                )
                session.add(row)
                await session.flush()
                return MemoryRecord.from_row(row)
        except IntegrityError as exc:
            raise MemoryConflict("相同 memory_key 已被其他请求创建") from exc

    async def save_confirmed_preference(
        self,
        *,
        memory_key: str,
        content: str,
        source_run_id: str,
        expected_version: int,
    ) -> MemoryRecord:
        """Agent 工具在用户批准后保存；新建使用 version=0，更新必须精确匹配。"""
        async with self.sessions() as session:
            row = await session.scalar(
                select(MemoryRow).where(
                    MemoryRow.scope_key == self.scope_key,
                    MemoryRow.category == "preference",
                    MemoryRow.memory_key == memory_key,
                )
            )
            if row is None:
                if expected_version != 0:
                    raise MemoryConflict("偏好尚不存在，新建时 expected_version 必须为 0")
                return await self.create_active(
                    category="preference",
                    memory_key=memory_key,
                    content=content,
                    source_run_id=source_run_id,
                )
            memory_id = row.id
        return await self.update(
            memory_id, content=content, expected_version=expected_version, source_run_id=source_run_id
        )

    async def update(
        self,
        memory_id: str,
        *,
        content: str,
        expected_version: int,
        source_run_id: str | None = None,
    ) -> MemoryRecord:
        now = _now()
        async with self.sessions.begin() as session:
            changed = await session.execute(
                update(MemoryRow)
                .where(
                    MemoryRow.id == memory_id,
                    MemoryRow.scope_key == self.scope_key,
                    MemoryRow.status == "active",
                    MemoryRow.version == expected_version,
                )
                .values(
                    content=content,
                    source_run_id=source_run_id,
                    version=MemoryRow.version + 1,
                    updated_at=now,
                )
            )
            row = await session.get(MemoryRow, memory_id, populate_existing=True)
            if row is None or row.scope_key != self.scope_key:
                raise MemoryNotFound("偏好记忆不存在")
            if changed.rowcount != 1:
                raise MemoryConflict(f"偏好版本已变化，当前 version={row.version}")
            return MemoryRecord.from_row(row)

    async def delete(self, memory_id: str, *, expected_version: int) -> MemoryRecord:
        now = _now()
        async with self.sessions.begin() as session:
            changed = await session.execute(
                update(MemoryRow)
                .where(
                    MemoryRow.id == memory_id,
                    MemoryRow.scope_key == self.scope_key,
                    MemoryRow.status == "active",
                    MemoryRow.version == expected_version,
                )
                .values(status="deleted", version=MemoryRow.version + 1, updated_at=now)
            )
            row = await session.get(MemoryRow, memory_id, populate_existing=True)
            if row is None or row.scope_key != self.scope_key:
                raise MemoryNotFound("偏好记忆不存在")
            if changed.rowcount != 1:
                raise MemoryConflict(f"偏好版本已变化，当前 version={row.version}")
            return MemoryRecord.from_row(row)
