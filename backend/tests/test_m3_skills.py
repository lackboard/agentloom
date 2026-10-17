import asyncio
import hashlib
import time
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import StructuredTool
from pydantic import PrivateAttr

from agentloom.agents.factory import create_loom_agent
from agentloom.api import create_app
from agentloom.config import AppConfig, SkillsConfig
from agentloom.runtime.context import LoomContext
from agentloom.skills import SkillLoader, SkillValidationError


def _write_skill(
    root: Path,
    *,
    name: str = "restricted",
    body: str = "正文中的唯一标记：BODY_V1",
    allowed_tools: tuple[str, ...] = ("permitted",),
) -> Path:
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "SKILL.md"
    allowed = "\n".join(f"  - {item}" for item in allowed_tools)
    path.write_text(
        f"---\nname: {name}\ndescription: 受限测试技能\nallowed-tools:\n{allowed}\n---\n\n{body}\n",
        encoding="utf-8",
    )
    return path


def _context(loader: SkillLoader, *, run_id: str = "run-1") -> LoomContext:
    # 这些测试只触发 Skill 工具，其他服务不会被访问。
    return LoomContext(
        thread_id="00000000-0000-0000-0000-000000000001",
        run_id=run_id,
        workspace=None,  # type: ignore[arg-type]
        artifacts=None,  # type: ignore[arg-type]
        skills=loader,
    )


class SkillPolicyProbeModel(BaseChatModel):
    """先加载 Skill，再故意猜一个已经从 schema 隐藏的工具。"""

    _bound_tool_names: list[list[str]] = PrivateAttr(default_factory=list)
    _system_prompts: list[str] = PrivateAttr(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "skill-policy-probe"

    def bind_tools(self, tools, **kwargs):
        self._bound_tool_names.append([tool.name for tool in tools])
        return self

    def _generate(self, messages: list[AnyMessage], stop=None, run_manager=None, **kwargs) -> ChatResult:
        system = next((message for message in messages if isinstance(message, SystemMessage)), None)
        self._system_prompts.append(str(system.content) if system else "")
        tool_messages = [message for message in messages if isinstance(message, ToolMessage)]
        if not tool_messages:
            answer = AIMessage(
                content="",
                tool_calls=[{"name": "load_skill", "args": {"name": "restricted"}, "id": "load-1"}],
            )
        elif tool_messages[-1].name == "load_skill":
            answer = AIMessage(
                content="",
                tool_calls=[{"name": "dangerous", "args": {}, "id": "guess-1"}],
            )
        else:
            answer = AIMessage(content=f"已处理拒绝：{tool_messages[-1].content}")
        return ChatResult(generations=[ChatGeneration(message=answer)])


class CaptureModel(BaseChatModel):
    _system_prompts: list[str] = PrivateAttr(default_factory=list)
    _bound_tool_names: list[list[str]] = PrivateAttr(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "skill-capture"

    def bind_tools(self, tools, **kwargs):
        self._bound_tool_names.append([tool.name for tool in tools])
        return self

    def _generate(self, messages: list[AnyMessage], stop=None, run_manager=None, **kwargs) -> ChatResult:
        system = next((message for message in messages if isinstance(message, SystemMessage)), None)
        self._system_prompts.append(str(system.content) if system else "")
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="done"))])


class ApprovalSkillSnapshotModel(BaseChatModel):
    """两次 Run 都猜 replace_file，用审批暂停验证旧快照与新策略。"""

    _system_prompts: list[str] = PrivateAttr(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "approval-skill-snapshot"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages: list[AnyMessage], stop=None, run_manager=None, **kwargs) -> ChatResult:
        system = next((message for message in messages if isinstance(message, SystemMessage)), None)
        self._system_prompts.append(str(system.content) if system else "")
        last = messages[-1]
        if isinstance(last, HumanMessage):
            is_new = "新任务" in str(last.content)
            old = "第二版" if is_new else "第一版"
            new = "第三版" if is_new else "第二版"
            answer = AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "replace_file",
                        "args": {
                            "path": "/mnt/user-data/workspace/note.txt",
                            "old": old,
                            "new": new,
                            "expected_sha256": hashlib.sha256(old.encode()).hexdigest(),
                        },
                        "id": "replace-new" if is_new else "replace-old",
                    }
                ],
            )
        elif isinstance(last, ToolMessage):
            answer = AIMessage(content=f"工具结果：{last.content}")
        else:
            raise TypeError("测试模型只接受 HumanMessage 或 ToolMessage")
        return ChatResult(generations=[ChatGeneration(message=answer)])


def _wait_run(client: TestClient, run_id: str, expected: set[str]) -> dict:
    for _ in range(400):
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] in expected:
            return run
        time.sleep(0.01)
    raise AssertionError(f"Run 未进入预期状态：{run}")


def test_loader_discovers_metadata_without_exposing_body_and_rejects_invalid_frontmatter(tmp_path: Path) -> None:
    _write_skill(tmp_path)
    loader = SkillLoader(tmp_path)

    metadata = loader.list_skills()
    snapshot = loader.load("restricted", activation="tool", run_id="run-1")

    assert [item.name for item in metadata] == ["restricted"]
    assert "BODY_V1" not in repr(metadata)
    assert snapshot.content == "正文中的唯一标记：BODY_V1"
    assert len(snapshot.content_hash) == 64
    assert snapshot.snapshot_ref.endswith(snapshot.content_hash)

    broken = tmp_path / "broken" / "SKILL.md"
    broken.parent.mkdir()
    broken.write_text("# missing frontmatter", encoding="utf-8")
    with pytest.raises(SkillValidationError, match="frontmatter"):
        SkillLoader(tmp_path)


def test_skills_api_returns_metadata_without_body(tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    _write_skill(skills_root)
    config = AppConfig(skills=SkillsConfig(directory=skills_root))
    app = create_app(tmp_path / "data", config=config, model=CaptureModel(), tools=[])

    with TestClient(app) as client:
        response = client.get("/api/skills")

    assert response.status_code == 200
    assert response.json() == {
        "skills": [
            {
                "name": "restricted",
                "description": "受限测试技能",
                "allowed_tools": ["permitted"],
            }
        ]
    }
    assert "BODY_V1" not in response.text


def test_loaded_skill_filters_schema_and_denies_a_guessed_hidden_tool(tmp_path: Path) -> None:
    async def scenario() -> None:
        _write_skill(tmp_path)
        loader = SkillLoader(tmp_path)
        executions = 0

        def dangerous() -> str:
            nonlocal executions
            executions += 1
            return "should-not-run"

        dangerous_tool = StructuredTool.from_function(
            func=dangerous,
            name="dangerous",
            description="测试用副作用工具。",
        )
        permitted_tool = StructuredTool.from_function(
            func=lambda: "ok",
            name="permitted",
            description="Skill 允许的测试工具。",
        )
        model = SkillPolicyProbeModel()
        agent = create_loom_agent(model=model, tools=[dangerous_tool, permitted_tool])

        result = await agent.ainvoke(
            {"messages": [HumanMessage(content="请使用合适的技能")], "current_run_id": "run-1"},
            context=_context(loader),
        )

        assert executions == 0
        assert "BODY_V1" not in model._system_prompts[0]
        assert "受限测试技能" in model._system_prompts[0]
        assert "BODY_V1" in model._system_prompts[1]
        assert "dangerous" in model._bound_tool_names[0]
        assert "dangerous" not in model._bound_tool_names[1]
        assert {"permitted", "list_skills", "load_skill"}.issubset(model._bound_tool_names[1])
        denied = next(
            message
            for message in result["messages"]
            if isinstance(message, ToolMessage) and message.name == "dangerous"
        )
        assert denied.status == "error"
        assert "SKILL_TOOL_DENIED" in str(denied.content)
        assert result["active_skill"]["content_hash"]

    asyncio.run(scenario())


def test_slash_activation_keeps_old_snapshot_while_a_new_run_reads_new_content(tmp_path: Path) -> None:
    async def scenario() -> None:
        skill_file = _write_skill(tmp_path)
        loader = SkillLoader(tmp_path)
        model = CaptureModel()
        agent = create_loom_agent(model=model, tools=[])

        first = await agent.ainvoke(
            {
                "messages": [HumanMessage(content="/restricted 执行任务")],
                "current_run_id": "run-1",
                "active_skill": None,
            },
            context=_context(loader, run_id="run-1"),
        )
        old_hash = first["active_skill"]["content_hash"]
        _write_skill(tmp_path, body="正文中的唯一标记：BODY_V2", allowed_tools=("dangerous",))

        await agent.ainvoke(
            {
                "messages": [*first["messages"], HumanMessage(content="继续")],
                "current_run_id": "run-1",
                "active_skill": first["active_skill"],
            },
            context=_context(loader, run_id="run-1"),
        )
        second = await agent.ainvoke(
            {
                "messages": [HumanMessage(content="/restricted 新任务")],
                "current_run_id": "run-2",
                "active_skill": None,
            },
            context=_context(loader, run_id="run-2"),
        )

        assert "BODY_V1" in model._system_prompts[1]
        assert "BODY_V2" not in model._system_prompts[1]
        assert "BODY_V2" in model._system_prompts[2]
        assert second["active_skill"]["content_hash"] != old_hash
        assert second["active_skill"]["allowed_tools"] == ["dangerous"]
        assert skill_file.exists()

    asyncio.run(scenario())


def test_waiting_approval_uses_frozen_skill_while_new_run_loads_changed_policy(tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    skill_file = _write_skill(skills_root, allowed_tools=("replace_file",))
    config = AppConfig(skills=SkillsConfig(directory=skills_root))
    model = ApprovalSkillSnapshotModel()
    app = create_app(tmp_path / "data", config=config, model=model)

    with TestClient(app) as client:
        thread_id = client.post("/api/threads", json={}).json()["thread_id"]
        path = "/mnt/user-data/workspace/note.txt"
        app.state.workspace.write_text(thread_id, path, "第一版")
        first = client.post(
            f"/api/threads/{thread_id}/runs",
            json={
                "text": "/restricted 修改旧任务",
                "attachment_ids": [],
                "client_request_id": str(uuid4()),
            },
        ).json()
        waiting = _wait_run(client, first["run_id"], {"waiting_input"})
        approval = client.get(f"/api/runs/{first['run_id']}/approvals").json()["items"][0]

        # 暂停以后改变正文和权限；恢复必须继续使用 checkpoint 中的 V1 快照。
        _write_skill(skills_root, body="正文中的唯一标记：BODY_V2", allowed_tools=("permitted",))
        resolved = client.post(
            f"/api/approvals/{waiting['pending_approval_id']}/resolve",
            json={"payload_hash": approval["payload_hash"], "decision": "approve", "reason": None},
        )
        assert resolved.status_code == 200
        assert _wait_run(client, first["run_id"], {"succeeded"})["status"] == "succeeded"
        assert app.state.workspace.read_text(thread_id, path).content == "第二版"
        first_ledger = client.get(f"/api/runs/{first['run_id']}/tool-executions").json()["items"]
        assert [(item["status"], item["attempts"]) for item in first_ledger] == [("succeeded", 1)]

        second = client.post(
            f"/api/threads/{thread_id}/runs",
            json={
                "text": "/restricted 新任务",
                "attachment_ids": [],
                "client_request_id": str(uuid4()),
            },
        ).json()
        assert _wait_run(client, second["run_id"], {"succeeded"})["status"] == "succeeded"
        assert app.state.workspace.read_text(thread_id, path).content == "第二版"
        second_ledger = client.get(f"/api/runs/{second['run_id']}/tool-executions").json()["items"]
        assert [(item["status"], item["error_code"], item["attempts"]) for item in second_ledger] == [
            ("failed", "SKILL_TOOL_DENIED", 1)
        ]
        assert client.get(f"/api/runs/{second['run_id']}/approvals").json()["items"] == []

    assert "BODY_V1" in model._system_prompts[1]
    assert "BODY_V2" in model._system_prompts[2]
    assert skill_file.exists()
