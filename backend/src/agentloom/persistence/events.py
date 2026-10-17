"""为同一 Run 原子分配事件序号。"""

from sqlalchemy import update

from agentloom.persistence.models import RunEventRow, RunRow


async def append_run_event(
    session,
    *,
    run_id: str,
    event_type: str,
    scope: str,
    payload_json: str,
    created_at: str,
) -> int:
    """用数据库自增语句分配 seq，避免并发写入者读到相同旧值。"""
    result = await session.execute(
        update(RunRow)
        .where(RunRow.id == run_id)
        .values(next_event_seq=RunRow.next_event_seq + 1)
        .returning(RunRow.next_event_seq)
    )
    next_seq = result.scalar_one_or_none()
    if next_seq is None:
        raise RuntimeError(f"Run 不存在，无法追加事件：{run_id}")
    seq = int(next_seq) - 1
    session.add(
        RunEventRow(
            run_id=run_id,
            seq=seq,
            event_type=event_type,
            scope=scope,
            payload_json=payload_json,
            created_at=created_at,
        )
    )
    return seq
