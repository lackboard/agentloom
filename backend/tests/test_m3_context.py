import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import StructuredTool
from pydantic import PrivateAttr

from agentloom.agents.context import ContextCompactionMiddleware
from agentloom.agents.factory import create_loom_agent
from agentloom.api import create_app
from agentloom.config import AppConfig, ContextConfig, ModelConfig, ModelsConfig
from agentloom.runtime.context import LoomContext
from agentloom.sandbox import PathOutOfScope, WorkspaceService
from agentloom.tools.files import read_file


def _large_result(label: str) -> str:
    return f"{label}|" + (label * 2500)


LARGE_TOOL = StructuredTool.from_function(
    func=_large_result,
    name="large_result",
    description="返回确定性的大文本，用于验证结果外置。",
)


class OneLargeResultModel(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "one-large-result"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages: list[AnyMessage], stop=None, run_manager=None, **kwargs) -> ChatResult:
        results = [item for item in messages if isinstance(item, ToolMessage)]
        if not results:
            answer = AIMessage(
                content="",
                tool_calls=[{"name": "large_result", "args": {"label": "A"}, "id": "large-1"}],
            )
        elif results[-1].name == "large_result":
            reference = json.loads(str(results[-1].content))
            answer = AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "read_file",
                        "args": {"path": reference["full_result_path"], "start_char": 0, "max_chars": 32},
                        "id": "read-1",
                    }
                ],
            )
        else:
            answer = AIMessage(content="已通过引用读取完整结果的首个分块。")
        return ChatResult(generations=[ChatGeneration(message=answer)])


class CompactionWorkflowModel(BaseChatModel):
    """四次工具调用后结束；摘要调用由提示词识别并单独计数。"""

    _workflow_calls: int = PrivateAttr(default=0)
    _summary_calls: int = PrivateAttr(default=0)

    @property
    def _llm_type(self) -> str:
        return "compaction-workflow"

    @property
    def summary_calls(self) -> int:
        return self._summary_calls

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages: list[AnyMessage], stop=None, run_manager=None, **kwargs) -> ChatResult:
        if any(
            isinstance(message, HumanMessage)
            and isinstance(message.content, str)
            and message.content.startswith("你是 Agent 上下文压缩器")
            for message in messages
        ):
            self._summary_calls += 1
            answer = AIMessage(
                content="摘要：早期工具步骤已经完成；完整结果保存在 tool-results 引用中。",
                usage_metadata={"input_tokens": 30, "output_tokens": 10, "total_tokens": 40},
            )
        elif self._workflow_calls < 4:
            index = self._workflow_calls
            self._workflow_calls += 1
            answer = AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "large_result",
                        "args": {"label": f"G{index}"},
                        "id": f"group-{index}",
                    }
                ],
                usage_metadata={"input_tokens": 20, "output_tokens": 5, "total_tokens": 25},
            )
        else:
            self._workflow_calls += 1
            answer = AIMessage(
                content="四个步骤均已完成。",
                usage_metadata={"input_tokens": 20, "output_tokens": 5, "total_tokens": 25},
            )
        return ChatResult(generations=[ChatGeneration(message=answer)])


class FailingSummaryModel(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "failing-summary"

    def _generate(self, messages: list[AnyMessage], stop=None, run_manager=None, **kwargs) -> ChatResult:
        raise RuntimeError("planned summary failure")


class FailingSummaryWorkflowModel(BaseChatModel):
    """正式调用持续请求工具，摘要调用固定失败。"""

    _workflow_calls: int = PrivateAttr(default=0)
    _summary_calls: int = PrivateAttr(default=0)

    @property
    def _llm_type(self) -> str:
        return "failing-summary-workflow"

    @property
    def summary_calls(self) -> int:
        return self._summary_calls

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages: list[AnyMessage], stop=None, run_manager=None, **kwargs) -> ChatResult:
        if any(
            isinstance(message, HumanMessage)
            and isinstance(message.content, str)
            and message.content.startswith("你是 Agent 上下文压缩器")
            for message in messages
        ):
            self._summary_calls += 1
            raise RuntimeError("planned summary failure")
        index = self._workflow_calls
        self._workflow_calls += 1
        answer = AIMessage(
            content="",
            tool_calls=[{"name": "large_result", "args": {"label": f"F{index}"}, "id": f"fail-{index}"}],
            usage_metadata={"input_tokens": 20, "output_tokens": 5, "total_tokens": 25},
        )
        return ChatResult(generations=[ChatGeneration(message=answer)])


def _tool_group(number: int, *, duplicate_result: bool = False) -> list[AnyMessage]:
    call_id = f"call-{number}"
    messages: list[AnyMessage] = [
        AIMessage(
            id=f"ai-{number}",
            content="",
            tool_calls=[{"name": "lookup", "args": {"n": number}, "id": call_id}],
        ),
        ToolMessage(id=f"tool-{number}", content=f"result-{number}", tool_call_id=call_id, name="lookup"),
    ]
    if duplicate_result:
        messages.append(
            ToolMessage(
                id=f"tool-{number}-duplicate",
                content=f"duplicate-{number}",
                tool_call_id=call_id,
                name="lookup",
            )
        )
    return messages


def _wait(client: TestClient, run_id: str) -> dict:
    for _ in range(400):
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] in {"succeeded", "failed", "cancelled"}:
            return run
        time.sleep(0.01)
    raise AssertionError(f"Run 未结束：{run}")


def test_large_tool_result_is_externalized_before_the_model_sees_it(tmp_path: Path) -> None:
    async def scenario() -> None:
        workspace = WorkspaceService(tmp_path / "threads")
        thread_id = str(uuid4())
        run_id = str(uuid4())
        agent = create_loom_agent(
            model=OneLargeResultModel(),
            tools=[LARGE_TOOL, read_file],
            tool_preview_bytes=512,
        )
        result = await agent.ainvoke(
            {"messages": [HumanMessage(content="生成大结果")], "current_run_id": run_id},
            context=LoomContext(
                thread_id=thread_id,
                run_id=run_id,
                workspace=workspace,
                artifacts=None,  # type: ignore[arg-type]
            ),
        )

        tool_messages = [message for message in result["messages"] if isinstance(message, ToolMessage)]
        payload = json.loads(str(next(message for message in tool_messages if message.name == "large_result").content))
        read_payload = json.loads(
            str(next(message for message in tool_messages if message.name == "read_file").content)
        )
        stored = workspace.read_text(thread_id, payload["full_result_path"])

        assert payload["externalized"] is True
        assert payload["truncated"] is True
        assert len(payload["preview"].encode("utf-8")) <= 512
        assert stored.content == _large_result("A")
        assert stored.sha256 == payload["sha256"]
        assert read_payload["content"] == _large_result("A")[:32]
        assert read_payload["truncated"] is True
        with pytest.raises(PathOutOfScope):
            workspace.write_text(thread_id, payload["full_result_path"], "禁止覆盖")

    asyncio.run(scenario())


def test_compaction_keeps_current_request_and_two_complete_tool_groups() -> None:
    middleware = ContextCompactionMiddleware(
        FailingSummaryModel(),
        [],
        context_window=10000,
        max_output_tokens=100,
        compaction_fraction=0.01,
        max_model_attempts=24,
    )
    current = HumanMessage(id="current-user", content="完成当前任务")
    messages = [current, *_tool_group(1, duplicate_result=True), *_tool_group(2), *_tool_group(3)]
    state = {"messages": messages, "current_run_id": "run-1", "todos": [{"id": "t1", "status": "open"}]}

    plan = middleware.plan(state, force=True)  # type: ignore[arg-type]

    assert plan is not None
    summarized_ids = [message.id for message in plan.messages_to_summarize]
    preserved_ids = [message.id for message in plan.preserved_messages]
    assert summarized_ids == ["ai-1", "tool-1", "tool-1-duplicate"]
    assert preserved_ids == ["current-user", "ai-2", "tool-2", "ai-3", "tool-3"]


def test_summary_failure_keeps_original_messages_and_counts_the_attempt() -> None:
    async def scenario() -> None:
        middleware = ContextCompactionMiddleware(
            FailingSummaryModel(),
            [],
            context_window=10000,
            max_output_tokens=100,
            compaction_fraction=0.01,
            max_model_attempts=24,
        )
        messages = [HumanMessage(id="current", content="当前任务"), *_tool_group(1), *_tool_group(2), *_tool_group(3)]
        state = {"messages": messages, "current_run_id": "run-1"}

        update = await middleware.abefore_model(state, SimpleNamespace(context=None))  # type: ignore[arg-type]

        assert update == {"run_model_call_count": 1, "thread_model_call_count": 1}
        assert state["messages"] == messages
        assert "summary_text" not in state

    asyncio.run(scenario())


def test_repeated_summary_failure_stops_at_the_shared_model_budget(tmp_path: Path) -> None:
    model = FailingSummaryWorkflowModel()
    config = AppConfig(
        models=ModelsConfig(default=ModelConfig(context_window=10000, max_output_tokens=100)),
        runtime={"max_model_attempts_per_run": 5},
        context=ContextConfig(compaction_fraction=0.01, tool_preview_bytes=256),
    )
    app = create_app(tmp_path, config=config, model=model, tools=[LARGE_TOOL])

    with TestClient(app) as client:
        thread_id = client.post("/api/threads", json={}).json()["thread_id"]
        response = client.post(
            f"/api/threads/{thread_id}/runs",
            json={"text": "持续执行直到预算终止", "attachment_ids": [], "client_request_id": str(uuid4())},
        )
        run = _wait(client, response.json()["run_id"])

    assert run["status"] == "failed"
    assert run["usage"]["model_attempts"] == 5
    assert model.summary_calls == 1
    assert "模型调用预算已经耗尽" in run["error"]["message"]


def test_api_compaction_counts_summary_and_preserves_full_ui_history(tmp_path: Path) -> None:
    model = CompactionWorkflowModel()
    config = AppConfig(
        models=ModelsConfig(
            default=ModelConfig(
                context_window=1800,
                max_output_tokens=100,
            )
        ),
        context=ContextConfig(compaction_fraction=0.40, tool_preview_bytes=256),
    )
    app = create_app(tmp_path, config=config, model=model, tools=[LARGE_TOOL])

    with TestClient(app) as client:
        thread_id = client.post("/api/threads", json={}).json()["thread_id"]
        response = client.post(
            f"/api/threads/{thread_id}/runs",
            json={"text": "连续执行四个大结果步骤", "attachment_ids": [], "client_request_id": str(uuid4())},
        )
        run_id = response.json()["run_id"]
        run = _wait(client, run_id)
        messages = client.get(f"/api/threads/{thread_id}/messages").json()["items"]

        assert run["status"] == "succeeded"
        assert model.summary_calls >= 1
        assert run["usage"]["model_attempts"] == 5 + model.summary_calls
        assert [item["role"] for item in messages].count("tool") == 4
        assert [item["role"] for item in messages].count("assistant") == 5
        assert all("externalized" in item["content"]["text"] for item in messages if item["role"] == "tool")
        stored = list((tmp_path / "threads" / thread_id / "tool-results" / run_id).glob("*.txt"))
        assert len(stored) == 4
