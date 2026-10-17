"""进程内事件通知；持久化 run_events 才是可回放事实。"""

import asyncio
from collections import defaultdict


class EventBroker:
    """用版本号唤醒 SSE 订阅者，避免查询与等待之间漏通知。"""

    def __init__(self) -> None:
        self._versions: defaultdict[str, int] = defaultdict(int)
        self._conditions: defaultdict[str, asyncio.Condition] = defaultdict(asyncio.Condition)

    def version(self, run_id: str) -> int:
        return self._versions[run_id]

    def notify(self, run_id: str) -> None:
        self._versions[run_id] += 1
        condition = self._conditions[run_id]

        async def wake() -> None:
            async with condition:
                condition.notify_all()

        asyncio.create_task(wake())

    async def wait_for_change(self, run_id: str, version: int, *, timeout: float = 1.0) -> bool:
        condition = self._conditions[run_id]
        if self._versions[run_id] != version:
            return True
        try:
            async with asyncio.timeout(timeout):
                async with condition:
                    await condition.wait_for(lambda: self._versions[run_id] != version)
            return True
        except TimeoutError:
            return False
