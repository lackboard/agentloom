import asyncio
import json
import sqlite3
import time
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import PrivateAttr

from agentloom.api import create_app
from agentloom.artifacts import ArtifactService
from agentloom.config import AppConfig, RuntimeConfig
from agentloom.models.fake import OfflineChatModel
from agentloom.persistence.database import create_sessionmaker, migrate_database
from agentloom.runtime.ledger import ToolLedgerService
from agentloom.runtime.manager import RunManager
from agentloom.sandbox import WorkspaceService
from agentloom.subagents import SubagentExecutor, SubagentRequest, SubagentTaskRepository


def _usage_message(content: str = "", *, tool_calls=None) -> AIMessage:
    return AIMessage(
        content=content,
        tool_calls=tool_calls or [],
        usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
    )


class SingleCoderModel(OfflineChatModel):
    """Lead 委派一次，Coder 在私有目录写文件，Lead 再消费结构化结果。"""

    _bound_tool_names: list[set[str]] = PrivateAttr(default_factory=list)

    def bind_tools(self, tools, **kwargs):
        self._bound_tool_names.append({tool.name for tool in tools})
        return self

    def _respond(self, messages):
        last = messages[-1]
        if isinstance(last, HumanMessage) and str(last.content).startswith("任务："):
            # 子 Agent 只能看见专门构造的任务消息，看不到父消息全文。
            assert "PARENT_PRIVATE" not in str(last.content)
            return _usage_message(
                tool_calls=[
                    {
                        "name": "list_dir",
                        "args": {"path": "/mnt/user-data/uploads"},
                        "id": "child-list-1",
                        "type": "tool_call",
                    }
                ]
            )
        if isinstance(last, ToolMessage) and last.name == "list_dir":
            payload = json.loads(last.content)
            if payload["path"] == "/mnt/user-data/uploads":
                child_path = f"/mnt/user-data/uploads/{payload['items'][0]['name']}"
                return _usage_message(
                    tool_calls=[
                        {
                            "name": "list_dir",
                            "args": {"path": child_path},
                            "id": "child-list-2",
                            "type": "tool_call",
                        }
                    ]
                )
            child_path = f"{payload['path']}/{payload['items'][0]['name']}"
            return _usage_message(
                tool_calls=[
                    {
                        "name": "read_file",
                        "args": {"path": child_path},
                        "id": "child-read-1",
                        "type": "tool_call",
                    }
                ]
            )
        if isinstance(last, ToolMessage) and last.name == "read_file":
            assert json.loads(last.content)["content"] == "父文件快照\n"
            return _usage_message(
                tool_calls=[
                    {
                        "name": "write_file",
                        "args": {
                            "path": "/mnt/user-data/workspace/child.txt",
                            "content": "只属于子任务\n",
                        },
                        "id": "child-write-1",
                        "type": "tool_call",
                    }
                ]
            )
        if isinstance(last, ToolMessage) and last.name == "write_file":
            payload = json.loads(last.content)
            if payload.get("ok") is True:
                # Coder 尝试越出自己的虚拟根目录，执行点必须拒绝。
                return _usage_message(
                    tool_calls=[
                        {
                            "name": "write_file",
                            "args": {
                                "path": "/mnt/user-data/workspace/../../parent.txt",
                                "content": "不能写到父目录",
                            },
                            "id": "child-escape-1",
                            "type": "tool_call",
                        }
                    ]
                )
            assert payload["error"]["code"] == "PATH_OUT_OF_SCOPE"
            return _usage_message(
                tool_calls=[
                    {
                        "name": "request_parent_action",
                        "args": {"tool_name": "bash", "command": "pytest -q"},
                        "id": "child-request-1",
                        "type": "tool_call",
                    }
                ]
            )
        if isinstance(last, ToolMessage) and last.name == "request_parent_action":
            # 故意作出无凭证声明，结果契约仍必须把 tests_passed 保持为 unverified。
            return _usage_message("已生成 child.txt；请 Lead 执行 pytest -q；我认为测试已经通过。")
        if isinstance(last, HumanMessage):
            return _usage_message(
                tool_calls=[
                    {
                        "name": "task",
                        "args": {
                            "agent_type": "coder",
                            "prompt": "创建 child.txt",
                            "expected_outputs": ["child.txt"],
                            "input_files": ["/mnt/user-data/workspace/source.txt"],
                        },
                        "id": "delegate-1",
                        "type": "tool_call",
                    }
                ]
            )
        if isinstance(last, ToolMessage) and last.name == "task":
            payload = json.loads(last.content)
            assert payload["result"]["status"] == "succeeded"
            assert payload["result"]["acceptance"]["tests_passed"] == "unverified"
            return _usage_message("Lead 已读取子任务结果并完成汇总。")
        raise AssertionError(f"未预期消息：{last!r}")


class FailingChildModel(SingleCoderModel):
    """子模型失败，但失败结果仍必须回到 Lead。"""

    def _respond(self, messages):
        last = messages[-1]
        if isinstance(last, HumanMessage) and str(last.content).startswith("任务："):
            raise RuntimeError("injected child failure")
        if isinstance(last, ToolMessage) and last.name == "task":
            payload = json.loads(last.content)
            assert payload["result"]["status"] == "failed"
            return _usage_message("Lead 已看到子任务失败并停止依赖该结果。")
        return super()._respond(messages)


class ParallelDelegationModel(OfflineChatModel):
    """一次提出五个 task；四个入场，其中一个 child 失败、一个尝试递归。"""

    _active_children: int = PrivateAttr(default=0)
    _max_active_children: int = PrivateAttr(default=0)

    @property
    def max_active_children(self) -> int:
        return self._max_active_children

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        first_human = next(message for message in messages if isinstance(message, HumanMessage))
        is_child = str(first_human.content).startswith("任务：")
        last = messages[-1]
        if is_child:
            self._active_children += 1
            self._max_active_children = max(self._max_active_children, self._active_children)
            try:
                await asyncio.sleep(0.08)
                task_text = str(first_human.content)
                if "FAIL" in task_text:
                    raise RuntimeError("injected sibling failure")
                if "NEST" in task_text and isinstance(last, HumanMessage):
                    answer = _usage_message(
                        tool_calls=[
                            {
                                "name": "task",
                                "args": {"agent_type": "researcher", "prompt": "nested"},
                                "id": "nested-call",
                                "type": "tool_call",
                            }
                        ]
                    )
                elif "NEST" in task_text and isinstance(last, ToolMessage):
                    answer = _usage_message(f"递归委派被拒绝：{last.content}")
                else:
                    answer = _usage_message(f"完成：{task_text.splitlines()[0]}")
            finally:
                self._active_children -= 1
        elif isinstance(last, HumanMessage):
            calls = []
            for index, prompt in enumerate(["NEST", "FAIL", "OK-2", "OK-3"]):
                calls.append(
                    {
                        "name": "task",
                        "args": {"agent_type": "researcher", "prompt": prompt},
                        "id": f"parallel-{index}",
                        "type": "tool_call",
                    }
                )
            answer = _usage_message(tool_calls=calls)
        elif not any(
            isinstance(message, ToolMessage) and message.tool_call_id == "parallel-over" for message in messages
        ):
            # 前四个并发任务都结束后再提交第 5 个，稳定验证总量上限。
            answer = _usage_message(
                tool_calls=[
                    {
                        "name": "task",
                        "args": {"agent_type": "researcher", "prompt": "OVER-LIMIT"},
                        "id": "parallel-over",
                        "type": "tool_call",
                    }
                ]
            )
        else:
            answer = _usage_message("Lead 已分别收到所有子任务状态并完成汇总。")
        return ChatResult(generations=[ChatGeneration(message=answer)])


class BlockingChildrenModel(OfflineChatModel):
    """两个 child 都阻塞，供父 Run 取消测试。"""

    _started: int = PrivateAttr(default=0)
    _cancelled: int = PrivateAttr(default=0)

    @property
    def started(self) -> int:
        return self._started

    @property
    def cancelled(self) -> int:
        return self._cancelled

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        first_human = next(message for message in messages if isinstance(message, HumanMessage))
        if str(first_human.content).startswith("任务："):
            self._started += 1
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self._cancelled += 1
                raise
        last = messages[-1]
        if isinstance(last, HumanMessage):
            answer = _usage_message(
                tool_calls=[
                    {
                        "name": "task",
                        "args": {"agent_type": "researcher", "prompt": f"BLOCK-{index}"},
                        "id": f"block-{index}",
                        "type": "tool_call",
                    }
                    for index in range(2)
                ]
            )
        else:
            answer = _usage_message("不应在取消后继续")
        return ChatResult(generations=[ChatGeneration(message=answer)])


class SharedBudgetModel(OfflineChatModel):
    """父一次模型、child 两次模型、父收尾一次；第 4 次应被共享预算拒绝。"""

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        first_human = next(message for message in messages if isinstance(message, HumanMessage))
        last = messages[-1]
        if str(first_human.content).startswith("任务："):
            if isinstance(last, HumanMessage):
                answer = _usage_message(
                    tool_calls=[{"name": "add", "args": {"a": 20, "b": 22}, "id": "child-add", "type": "tool_call"}]
                )
            else:
                answer = _usage_message("child 得到 42")
        elif isinstance(last, HumanMessage):
            answer = _usage_message(
                tool_calls=[
                    {
                        "name": "task",
                        "args": {"agent_type": "researcher", "prompt": "计算 20 + 22"},
                        "id": "budget-task",
                        "type": "tool_call",
                    }
                ]
            )
        else:
            answer = _usage_message("这一轮不应真的请求到模型")
        return ChatResult(generations=[ChatGeneration(message=answer)])


class OneShotChildModel(OfflineChatModel):
    _calls: int = PrivateAttr(default=0)

    @property
    def calls(self) -> int:
        return self._calls

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self._calls += 1
        return ChatResult(generations=[ChatGeneration(message=_usage_message("可复用的完成结果"))])


def _wait(client: TestClient, run_id: str) -> dict:
    for _ in range(500):
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] in {"succeeded", "failed", "cancelled"}:
            return run
        time.sleep(0.01)
    raise AssertionError(f"Run 未结束：{run}")


def _submit(client: TestClient, thread_id: str, text: str) -> str:
    response = client.post(
        f"/api/threads/{thread_id}/runs",
        json={"text": text, "attachment_ids": [], "client_request_id": str(uuid4())},
    )
    assert response.status_code == 202
    return response.json()["run_id"]


def test_single_coder_is_isolated_non_recursive_and_persisted(tmp_path) -> None:
    model = SingleCoderModel()
    app = create_app(tmp_path, config=AppConfig(), model=model)
    with TestClient(app) as client:
        thread_id = client.post("/api/threads", json={}).json()["thread_id"]
        app.state.workspace.write_text(
            thread_id,
            "/mnt/user-data/workspace/source.txt",
            "父文件快照\n",
        )
        run_id = _submit(client, thread_id, "PARENT_PRIVATE：请委派 Coder")
        assert _wait(client, run_id)["status"] == "succeeded"

        messages = client.get(f"/api/threads/{thread_id}/messages").json()["items"]
        tool_names = [item["content"]["name"] for item in messages if item["role"] == "tool"]
        assert tool_names == ["task"]
        assert messages[-1]["content"]["text"] == "Lead 已读取子任务结果并完成汇总。"

        connection = sqlite3.connect(tmp_path / "app.sqlite")
        row = connection.execute(
            "SELECT id, status, result_json, acceptance_json FROM subagent_tasks WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        events = connection.execute(
            "SELECT event_type FROM run_events WHERE run_id = ? AND event_type LIKE 'subagent.%' ORDER BY seq",
            (run_id,),
        ).fetchall()
        connection.close()
        assert row is not None and row[1] == "succeeded"
        result = json.loads(row[2])
        assert result["task_files"] == ["/mnt/user-data/workspace/child.txt"]
        assert result["requires_parent_action"] == {"tool": "bash", "command": "pytest -q"}
        assert json.loads(row[3])["tests_passed"] == "unverified"
        assert [event[0] for event in events] == ["subagent.queued", "subagent.started", "subagent.finished"]

        task_id = row[0]
        child_file = app.state.workspace.thread_root(thread_id) / "tasks" / task_id / "workspace" / "child.txt"
        parent_file = app.state.workspace.thread_root(thread_id) / "workspace" / "child.txt"
        assert child_file.read_text(encoding="utf-8") == "只属于子任务\n"
        assert not parent_file.exists()
        assert not (app.state.workspace.thread_root(thread_id) / "parent.txt").exists()

        # Lead 能看见 task；任一 child schema 都不能看见 task、bash 或父目录替换工具。
        assert any("task" in names for names in model._bound_tool_names)
        child_schemas = [names for names in model._bound_tool_names if "write_file" in names and "task" not in names]
        assert child_schemas
        assert all({"task", "bash", "replace_file"}.isdisjoint(names) for names in child_schemas)
        assert "task" not in {tool.name for tool in app.state.subagents.tools_for("researcher")}
        assert "write_file" not in {tool.name for tool in app.state.subagents.tools_for("researcher")}


def test_child_failure_is_returned_to_lead_and_not_swallowed(tmp_path) -> None:
    app = create_app(tmp_path, config=AppConfig(), model=FailingChildModel())
    with TestClient(app) as client:
        thread_id = client.post("/api/threads", json={}).json()["thread_id"]
        app.state.workspace.write_text(
            thread_id,
            "/mnt/user-data/workspace/source.txt",
            "父文件快照\n",
        )
        run_id = _submit(client, thread_id, "请委派一个会失败的 Coder")
        # Lead 明确消费失败结果后可以正常结束；子任务本身仍保持 failed。
        assert _wait(client, run_id)["status"] == "succeeded"
        messages = client.get(f"/api/threads/{thread_id}/messages").json()["items"]
        task_message = next(item for item in messages if item["role"] == "tool")
        payload = json.loads(task_message["content"]["text"])
        assert payload["ok"] is False
        assert payload["result"]["error"] == {
            "code": "RuntimeError",
            "message": "injected child failure",
        }

        connection = sqlite3.connect(tmp_path / "app.sqlite")
        row = connection.execute(
            "SELECT status, result_json FROM subagent_tasks WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        connection.close()
        assert row is not None and row[0] == "failed"
        assert json.loads(row[1])["error"]["code"] == "RuntimeError"


def test_parallel_partial_failure_recursion_denial_and_total_limit(tmp_path) -> None:
    model = ParallelDelegationModel()
    config = AppConfig(runtime=RuntimeConfig(max_subagents_per_run=4, max_running_subagents=2))
    app = create_app(tmp_path, config=config, model=model)
    with TestClient(app) as client:
        thread_id = client.post("/api/threads", json={}).json()["thread_id"]
        run_id = _submit(client, thread_id, "并行委派五项，其中一个失败并诱导递归")
        assert _wait(client, run_id)["status"] == "succeeded"

        messages = client.get(f"/api/threads/{thread_id}/messages").json()["items"]
        task_messages = [item for item in messages if item["role"] == "tool"]
        assert len(task_messages) == 5
        payloads = [json.loads(item["content"]["text"]) for item in task_messages]
        results = [payload["result"] for payload in payloads if "result" in payload]
        rejected = [payload["error"] for payload in payloads if "error" in payload]
        assert sorted(result["status"] for result in results) == ["failed", "succeeded", "succeeded", "succeeded"]
        assert rejected == [{"code": "SUBAGENT_LIMIT_EXCEEDED", "message": "每个 Run 最多创建 4 个子任务"}]
        assert any("递归委派被拒绝" in result["summary"] for result in results)
        assert model.max_active_children == 2
        assert app.state.subagents.active_count(run_id) == 0

        connection = sqlite3.connect(tmp_path / "app.sqlite")
        rows = connection.execute(
            "SELECT status, result_json FROM subagent_tasks WHERE run_id = ? ORDER BY created_at",
            (run_id,),
        ).fetchall()
        connection.close()
        assert len(rows) == 4
        assert sorted(row[0] for row in rows) == ["failed", "succeeded", "succeeded", "succeeded"]
        assert sum("nested-call" in row[1] for row in rows) == 0


def test_parent_cancel_stops_all_active_children(tmp_path) -> None:
    model = BlockingChildrenModel()
    app = create_app(tmp_path, config=AppConfig(), model=model)
    with TestClient(app) as client:
        thread_id = client.post("/api/threads", json={}).json()["thread_id"]
        run_id = _submit(client, thread_id, "启动两个阻塞子任务")
        for _ in range(500):
            if model.started == 2 and app.state.subagents.active_count(run_id) == 2:
                break
            time.sleep(0.01)
        else:
            raise AssertionError("两个子任务没有同时进入执行")

        response = client.post(f"/api/runs/{run_id}/cancel")
        assert response.status_code == 200
        assert _wait(client, run_id)["status"] == "cancelled"
        assert model.cancelled == 2
        assert app.state.subagents.active_count(run_id) == 0

        connection = sqlite3.connect(tmp_path / "app.sqlite")
        statuses = connection.execute(
            "SELECT status FROM subagent_tasks WHERE run_id = ? ORDER BY created_at",
            (run_id,),
        ).fetchall()
        open_tools = connection.execute(
            "SELECT count(*) FROM tool_executions WHERE run_id = ? AND status IN ('prepared','running','uncertain')",
            (run_id,),
        ).fetchone()[0]
        connection.close()
        assert statuses == [("cancelled",), ("cancelled",)]
        assert open_tools == 0


def test_shared_model_budget_counts_lead_and_child(tmp_path) -> None:
    config = AppConfig(
        runtime=RuntimeConfig(
            max_model_attempts_per_run=3,
            max_tool_executions_per_run=10,
        )
    )
    app = create_app(tmp_path, config=config, model=SharedBudgetModel())
    with TestClient(app) as client:
        thread_id = client.post("/api/threads", json={}).json()["thread_id"]
        run_id = _submit(client, thread_id, "验证 Lead 和 child 共享模型预算")
        run = _wait(client, run_id)
        assert run["status"] == "failed"
        assert run["usage"]["model_attempts"] == 3
        assert run["usage"]["tool_executions"] == 2  # task + child add
        assert "RunBudgetExceeded" in run["error"]["message"]

        connection = sqlite3.connect(tmp_path / "app.sqlite")
        subtask = connection.execute(
            "SELECT status, input_tokens, output_tokens FROM subagent_tasks WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        connection.close()
        assert subtask is not None and subtask[0] == "succeeded"


def test_shared_tool_budget_stops_child_handler_before_execution(tmp_path) -> None:
    config = AppConfig(
        runtime=RuntimeConfig(
            max_model_attempts_per_run=6,
            max_tool_executions_per_run=1,
        )
    )
    app = create_app(tmp_path, config=config, model=SharedBudgetModel())
    with TestClient(app) as client:
        thread_id = client.post("/api/threads", json={}).json()["thread_id"]
        run_id = _submit(client, thread_id, "验证 child 与 Lead 共享工具预算")
        run = _wait(client, run_id)
        # Lead 收到结构化失败结果后仍可收尾；add 处理器没有获得第 2 个工具名额。
        assert run["status"] == "succeeded"
        assert run["usage"]["tool_executions"] == 1

        connection = sqlite3.connect(tmp_path / "app.sqlite")
        subtask = connection.execute(
            "SELECT status, result_json FROM subagent_tasks WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        connection.close()
        assert subtask is not None and subtask[0] == "failed"
        assert json.loads(subtask[1])["error"]["code"] == "RUN_BUDGET_EXCEEDED"


def test_restart_interrupts_active_child_but_completed_result_is_reusable(tmp_path: Path) -> None:
    async def prepare_orphan() -> tuple[str, str]:
        app_path = tmp_path / "app.sqlite"
        migrate_database(app_path)
        sessions = create_sessionmaker(app_path)
        manager = RunManager(sessions, model_name="fake")
        thread = await manager.create_thread()
        run = await manager.submit(thread.id, text="orphan", client_request_id=str(uuid4()))
        assert await manager.try_start(run.id)
        ledger = ToolLedgerService(sessions)
        execution = await ledger.prepare(
            run.id,
            "orphan-tool",
            "task",
            {"agent_type": "researcher", "prompt": "orphan"},
        )
        await ledger.begin(execution.id)
        repository = SubagentTaskRepository(sessions)
        record = await repository.prepare(
            run.id,
            "orphan-tool",
            "researcher",
            "orphan",
            timeout_seconds=120,
            expected_outputs=[],
            max_tasks_per_run=4,
        )
        assert await repository.start(record.id)
        await sessions.kw["bind"].dispose()
        return run.id, record.id

    run_id, task_id = asyncio.run(prepare_orphan())
    with TestClient(create_app(tmp_path, config=AppConfig(), model=OneShotChildModel())) as client:
        run = client.get(f"/api/runs/{run_id}").json()
        assert run["status"] == "interrupted"
        connection = sqlite3.connect(tmp_path / "app.sqlite")
        row = connection.execute(
            "SELECT status, result_json FROM subagent_tasks WHERE id = ?",
            (task_id,),
        ).fetchone()
        connection.close()
        assert row is not None and row[0] == "interrupted"
        assert json.loads(row[1])["error"]["code"] == "PROCESS_RESTARTED"

    async def completed_reuse() -> None:
        data_dir = tmp_path / "reuse"
        app_path = data_dir / "app.sqlite"
        migrate_database(app_path)
        sessions = create_sessionmaker(app_path)
        manager = RunManager(sessions, model_name="fake")
        thread = await manager.create_thread()
        run = await manager.submit(thread.id, text="reuse", client_request_id=str(uuid4()))
        assert await manager.try_start(run.id)
        workspace = WorkspaceService(data_dir / "threads")
        artifacts = ArtifactService(sessions, workspace)
        repository = SubagentTaskRepository(sessions)
        model = OneShotChildModel()
        executor = SubagentExecutor(
            model=model,
            tools=[],
            workspace=workspace,
            artifacts=artifacts,
            repository=repository,
        )
        request = SubagentRequest(agent_type="researcher", prompt="once")
        first = await executor.execute(
            request,
            parent_thread_id=thread.id,
            run_id=run.id,
            parent_tool_call_id="stable-parent-call",
        )
        second = await executor.execute(
            request,
            parent_thread_id=thread.id,
            run_id=run.id,
            parent_tool_call_id="stable-parent-call",
        )
        assert first == second
        assert model.calls == 1
        await sessions.kw["bind"].dispose()

    asyncio.run(completed_reuse())
