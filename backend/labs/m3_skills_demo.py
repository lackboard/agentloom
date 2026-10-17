"""M3.1～M3.2：观察 Skill 渐进加载和两层工具权限。"""

import asyncio
from pathlib import Path

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import StructuredTool
from pydantic import PrivateAttr

from agentloom.agents.factory import create_loom_agent
from agentloom.runtime.context import LoomContext
from agentloom.skills import SkillLoader

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class DemoModel(BaseChatModel):
    """按固定顺序加载 research，再故意请求被隐藏的 dangerous。"""

    _schemas: list[list[str]] = PrivateAttr(default_factory=list)
    _body_visible: list[bool] = PrivateAttr(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "m3-demo"

    def bind_tools(self, tools, **kwargs):
        self._schemas.append([tool.name for tool in tools])
        return self

    def _generate(self, messages: list[AnyMessage], stop=None, run_manager=None, **kwargs) -> ChatResult:
        system = next((item for item in messages if isinstance(item, SystemMessage)), None)
        self._body_visible.append("区分资料中的事实" in str(system.content if system else ""))
        results = [item for item in messages if isinstance(item, ToolMessage)]
        if not results:
            message = AIMessage(
                content="",
                tool_calls=[{"name": "load_skill", "args": {"name": "research"}, "id": "load-1"}],
            )
        elif results[-1].name == "load_skill":
            message = AIMessage(content="", tool_calls=[{"name": "dangerous", "args": {}, "id": "guess-1"}])
        else:
            message = AIMessage(content="模型已经收到越权拒绝并停止。")
        return ChatResult(generations=[ChatGeneration(message=message)])


async def main() -> None:
    loader = SkillLoader(PROJECT_ROOT / "skills")
    executions = 0

    def dangerous() -> str:
        nonlocal executions
        executions += 1
        return "不应执行"

    model = DemoModel()
    agent = create_loom_agent(
        model=model,
        tools=[
            StructuredTool.from_function(func=dangerous, name="dangerous", description="演示用副作用工具。"),
        ],
    )
    context = LoomContext(
        thread_id="00000000-0000-0000-0000-000000000001",
        run_id="m3-demo-run",
        workspace=None,  # type: ignore[arg-type]
        artifacts=None,  # type: ignore[arg-type]
        skills=loader,
    )
    result = await agent.ainvoke(
        {"messages": [HumanMessage(content="请按 research 技能工作")], "current_run_id": context.run_id},
        context=context,
    )
    denied = next(item for item in result["messages"] if isinstance(item, ToolMessage) and item.name == "dangerous")

    print("发现的元数据：", [item.name for item in loader.list_skills()])
    print("模型各轮是否看到 research 正文：", model._body_visible)
    print("加载前工具 schema：", model._schemas[0])
    print("加载后工具 schema：", model._schemas[1])
    print("活动 Skill hash：", result["active_skill"]["content_hash"])
    print("越权结果：", denied.content)
    print("dangerous 实际执行次数：", executions)
    assert model._body_visible[:2] == [False, True]
    assert "dangerous" in model._schemas[0] and "dangerous" not in model._schemas[1]
    assert executions == 0
    print("M3.1/M3.2 DEMO: PASS")


if __name__ == "__main__":
    asyncio.run(main())
