"""把 LangGraph 模型 chunk 合并成可持久化、可重连的文本增量。"""

import asyncio
from time import monotonic

from langchain_core.messages import AIMessageChunk

from agentloom.runtime.manager import RunManager


def _chunk_text(chunk: AIMessageChunk) -> str:
    """只提取当前 chunk 的可见文本；工具参数增量不进入聊天正文。"""
    if isinstance(chunk.content, str):
        return chunk.content
    return chunk.text


class PersistentMessageStream:
    """按字符数或短时间窗口合并增量，避免每个 token 都写一次 SQLite。"""

    def __init__(
        self,
        manager: RunManager,
        run_id: str,
        *,
        flush_interval_seconds: float = 0.05,
        flush_chars: int = 96,
    ) -> None:
        self.manager = manager
        self.run_id = run_id
        self.flush_interval_seconds = flush_interval_seconds
        self.flush_chars = flush_chars
        self._pending: dict[str, str] = {}
        self._timers: dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()
        self._closed = False
        self._error: BaseException | None = None
        self._last_flush = monotonic()

    async def add(self, chunk: object) -> None:
        if self._closed or not isinstance(chunk, AIMessageChunk):
            return
        message_id = str(chunk.id or "")
        delta = _chunk_text(chunk)
        if not message_id or not delta:
            return

        flush_value = ""
        async with self._lock:
            if self._error is not None:
                raise RuntimeError("持久化模型增量失败") from self._error
            value = self._pending.get(message_id, "") + delta
            self._pending[message_id] = value
            elapsed = monotonic() - self._last_flush
            if len(value) >= self.flush_chars or elapsed >= self.flush_interval_seconds:
                flush_value = self._pending.pop(message_id)
                self._last_flush = monotonic()
            elif message_id not in self._timers:
                self._timers[message_id] = asyncio.create_task(
                    self._flush_later(message_id),
                    name=f"agentloom-delta-flush-{message_id}",
                )
        if flush_value:
            await self.manager.append_message_delta(self.run_id, message_id, flush_value)

    async def _flush_later(self, message_id: str) -> None:
        current = asyncio.current_task()
        try:
            await asyncio.sleep(self.flush_interval_seconds)
            async with self._lock:
                value = self._pending.pop(message_id, "")
                if value:
                    self._last_flush = monotonic()
            if value:
                await self.manager.append_message_delta(self.run_id, message_id, value)
        except asyncio.CancelledError:
            raise
        except BaseException as exc:  # 后台定时任务不能产生无人读取的异常。
            self._error = exc
        finally:
            async with self._lock:
                if self._timers.get(message_id) is current:
                    self._timers.pop(message_id, None)

    async def close(self) -> None:
        """排空最后一批增量；重复关闭安全。"""
        if self._closed:
            return
        self._closed = True
        async with self._lock:
            timers = list(self._timers.values())
        # 已经取走 pending 的定时任务可能正在提交数据库；等待这段有界短任务，
        # 不能用取消把一个已准入的事件写入截断在事务中间。
        if timers:
            await asyncio.gather(*timers, return_exceptions=True)
        async with self._lock:
            pending = list(self._pending.items())
            self._pending.clear()
            error = self._error
        for message_id, value in pending:
            if value:
                await self.manager.append_message_delta(self.run_id, message_id, value)
        if error is not None:
            raise RuntimeError("持久化模型增量失败") from error
