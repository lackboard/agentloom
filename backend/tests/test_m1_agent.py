import asyncio

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from agentloom.agents.factory import create_loom_agent
from agentloom.models.fake import OfflineChatModel


@tool("add")
def changed_add(a: int, b: int) -> int:
    """返回可识别的替代结果，用于证明模型读取了真实工具消息。"""
    return 99


class ErrorThenStopModel(OfflineChatModel):
    """先产生无效工具请求，读到错误 ToolMessage 后明确结束。"""

    def _respond(self, messages):
        last = messages[-1]
        if isinstance(last, ToolMessage):
            return AIMessage(content=f"已读取工具错误：{last.content}")
        text = str(last.content)
        call = (
            {"name": "missing_tool", "args": {}, "id": "bad-call", "type": "tool_call"}
            if "未知" in text
            else {"name": "add", "args": {"a": 2}, "id": "bad-call", "type": "tool_call"}
        )
        return AIMessage(content="", tool_calls=[call])


def test_formal_agent_uses_real_tool_node_and_separate_checkpoint(tmp_path) -> None:
    async def scenario() -> None:
        checkpoint_path = tmp_path / "checkpoints.sqlite"
        async with AsyncSqliteSaver.from_conn_string(str(checkpoint_path)) as saver:
            await saver.setup()
            agent = create_loom_agent(model=OfflineChatModel(), checkpointer=saver)
            config = {"configurable": {"thread_id": "thread-1"}}
            first = await agent.ainvoke(
                {
                    "messages": [HumanMessage(content="请计算 2 + 3", id="input-1")],
                    "current_run_id": "run-1",
                    "todos": [{"id": "todo-1", "text": "calculate", "status": "open"}],
                    "artifact_ids": ["artifact-1"],
                },
                config=config,
            )
            assert [type(message) for message in first["messages"]] == [HumanMessage, AIMessage, ToolMessage, AIMessage]
            assert first["messages"][-2].content == "5"
            assert first["messages"][-2].tool_call_id == first["messages"][-3].tool_calls[0]["id"]
            assert first["current_run_id"] == "run-1"

            second = await agent.ainvoke(
                {
                    "messages": [HumanMessage(content="请计算 4 + 6", id="input-2")],
                    "current_run_id": "run-2",
                    "todos": [
                        {"id": "todo-1", "text": "calculate", "status": "done"},
                        {"id": "todo-2", "text": "explain", "status": "open"},
                    ],
                    "artifact_ids": ["artifact-1", "artifact-2"],
                },
                config=config,
            )
            assert second["messages"][-2].content == "10"
            assert second["current_run_id"] == "run-2"
            assert [item["status"] for item in second["todos"]] == ["done", "open"]
            assert second["artifact_ids"] == ["artifact-1", "artifact-2"]
            assert (await agent.aget_state(config)).values["messages"][-1].content.endswith("10")
        assert checkpoint_path.exists()
        async with AsyncSqliteSaver.from_conn_string(str(checkpoint_path)) as reopened:
            restored = create_loom_agent(model=OfflineChatModel(), checkpointer=reopened)
            snapshot = await restored.aget_state({"configurable": {"thread_id": "thread-1"}})
            assert snapshot.values["current_run_id"] == "run-2"
            assert snapshot.values["messages"][-1].content.endswith("10")

    asyncio.run(scenario())


def test_final_answer_consumes_actual_tool_result() -> None:
    agent = create_loom_agent(model=OfflineChatModel(), tools=[changed_add])
    result = agent.invoke({"messages": [HumanMessage(content="请计算 2 + 3")]})

    tool_result = next(message for message in result["messages"] if isinstance(message, ToolMessage))
    assert tool_result.content == "99"
    assert "最终答案：99" in result["messages"][-1].content


@pytest.mark.parametrize("input_text", ["调用未知工具", "使用错误参数"])
def test_invalid_tool_requests_return_bounded_error_feedback(input_text: str) -> None:
    agent = create_loom_agent(model=ErrorThenStopModel())
    result = agent.invoke({"messages": [HumanMessage(content=input_text)]})

    tool_results = [message for message in result["messages"] if isinstance(message, ToolMessage)]
    assert len(tool_results) == 1
    assert tool_results[0].tool_call_id == "bad-call"
    assert tool_results[0].status == "error"
    assert "已读取工具错误" in result["messages"][-1].content
