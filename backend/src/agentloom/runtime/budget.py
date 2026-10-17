"""Lead、摘要和子 Agent 共享的单 Run 硬预算。"""

from dataclasses import dataclass
from threading import Lock

from langchain.agents.middleware import AgentMiddleware


class RunBudgetExceeded(RuntimeError):
    """下一次真实模型或工具执行将超过 Run 的冻结预算。"""

    code = "RUN_BUDGET_EXCEEDED"


@dataclass(frozen=True)
class RunBudgetSnapshot:
    model_attempts: int
    tool_executions: int


class RunBudgetController:
    """用一个进程内原子计数器约束同一 Run 的所有嵌套执行链。"""

    def __init__(
        self,
        *,
        max_model_attempts: int,
        max_tool_executions: int,
        initial_model_attempts: int = 0,
        initial_tool_executions: int = 0,
    ) -> None:
        self.max_model_attempts = max_model_attempts
        self.max_tool_executions = max_tool_executions
        self._model_attempts = initial_model_attempts
        self._tool_executions = initial_tool_executions
        self._lock = Lock()

    def reserve_model_attempt(self) -> int:
        """在实际请求模型前占用一个名额；超限时不发出请求。"""
        with self._lock:
            if self._model_attempts >= self.max_model_attempts:
                raise RunBudgetExceeded(f"模型调用已达到每 Run 上限 {self.max_model_attempts}")
            self._model_attempts += 1
            return self._model_attempts

    def reserve_tool_execution(self) -> int:
        """在工具真正进入业务处理器前占用一个名额。"""
        with self._lock:
            if self._tool_executions >= self.max_tool_executions:
                raise RunBudgetExceeded(f"工具执行已达到每 Run 上限 {self.max_tool_executions}")
            self._tool_executions += 1
            return self._tool_executions

    def snapshot(self) -> RunBudgetSnapshot:
        with self._lock:
            return RunBudgetSnapshot(
                model_attempts=self._model_attempts,
                tool_executions=self._tool_executions,
            )


class SharedBudgetMiddleware(AgentMiddleware):
    """在实际模型请求和工具处理器入口统一消费 Run 预算。"""

    @staticmethod
    def _reserve_model(request) -> None:
        context = request.runtime.context
        if context is not None and context.budget is not None:
            context.budget.reserve_model_attempt()

    @staticmethod
    def _reserve_tool(request) -> None:
        context = request.runtime.context
        if context is not None and context.budget is not None:
            context.budget.reserve_tool_execution()

    def wrap_model_call(self, request, handler):
        self._reserve_model(request)
        return handler(request)

    async def awrap_model_call(self, request, handler):
        self._reserve_model(request)
        return await handler(request)

    def wrap_tool_call(self, request, handler):
        self._reserve_tool(request)
        return handler(request)

    async def awrap_tool_call(self, request, handler):
        self._reserve_tool(request)
        return await handler(request)
