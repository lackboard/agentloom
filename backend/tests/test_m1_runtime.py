import json
import sqlite3
import threading
import time
from uuid import uuid4

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from pydantic import PrivateAttr

from agentloom.api import create_app
from agentloom.config import AppConfig, RuntimeConfig
from agentloom.models.fake import OfflineChatModel


class BlockingOfflineModel(OfflineChatModel):
    """只阻塞第一次模型调用，便于观察运行中断线和取消。"""

    _started: threading.Event = PrivateAttr(default_factory=threading.Event)
    _release: threading.Event = PrivateAttr(default_factory=threading.Event)
    _calls: int = PrivateAttr(default=0)

    @property
    def started(self) -> threading.Event:
        return self._started

    @property
    def release(self) -> threading.Event:
        return self._release

    @property
    def calls(self) -> int:
        return self._calls

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self._calls += 1
        if self._calls == 1:
            self._started.set()
            if not self._release.wait(timeout=5):
                raise TimeoutError("测试没有释放阻塞模型")
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


class FailingOfflineModel(OfflineChatModel):
    """在模型边界抛错，验证失败终态与事件一致。"""

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        raise RuntimeError("planned model failure")


class RepeatingOfflineModel(OfflineChatModel):
    """忽略工具结果并持续提出调用，用于验证运行预算确实生效。"""

    def _respond(self, messages):
        call_number = 1 + sum(bool(isinstance(item, AIMessage) and item.tool_calls) for item in messages)
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "add",
                    "args": {"a": 2, "b": 3},
                    "id": f"repeat-{call_number}",
                    "type": "tool_call",
                }
            ],
            usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        )


@tool("add")
def failing_add(a: int, b: int) -> int:
    """模拟工具内部真实失败。"""
    raise RuntimeError("planned tool failure")


def _submit(client: TestClient, text: str = "请计算 2 + 3") -> tuple[str, str]:
    thread_id = client.post("/api/threads", json={}).json()["thread_id"]
    response = client.post(
        f"/api/threads/{thread_id}/runs",
        json={"text": text, "attachment_ids": [], "client_request_id": str(uuid4())},
    )
    assert response.status_code == 202
    return thread_id, response.json()["run_id"]


def _wait_status(client: TestClient, run_id: str, expected: set[str]) -> dict:
    for _ in range(200):
        result = client.get(f"/api/runs/{run_id}").json()
        if result["status"] in expected:
            return result
        time.sleep(0.01)
    raise AssertionError(f"Run {run_id} 没有进入 {expected}，最后状态为 {result['status']}")


def _sse_events(response) -> list[dict]:
    return [json.loads(line.removeprefix("data: ")) for line in response.text.splitlines() if line.startswith("data: ")]


def test_sse_reconnect_replays_missing_events_without_restarting_run(tmp_path) -> None:
    model = BlockingOfflineModel()
    app = create_app(tmp_path, config=AppConfig(), model=model)
    with TestClient(app) as client:
        thread_id, run_id = _submit(client)
        assert model.started.wait(timeout=2)
        running = _wait_status(client, run_id, {"running"})
        assert running["status"] == "running"

        # 模拟客户端已收到 seq=1/2 后断线；此时没有 SSE 连接持有后台任务。
        with sqlite3.connect(tmp_path / "app.sqlite") as connection:
            assert connection.execute(
                "SELECT seq,event_type FROM run_events WHERE run_id=? ORDER BY seq", (run_id,)
            ).fetchall() == [(1, "message.completed"), (2, "run.started")]
        model.release.set()
        finished = _wait_status(client, run_id, {"succeeded"})

        replay = client.get(f"/api/runs/{run_id}/events", params={"after_seq": 2})
        assert replay.status_code == 200
        events = _sse_events(replay)
        assert events and [event["seq"] for event in events] == list(range(3, events[-1]["seq"] + 1))
        assert events[-1]["type"] == "run.finished"
        assert events[-1]["data"] == {"status": "succeeded", "stop_reason": "completed"}

        last_only = _sse_events(
            client.get(f"/api/runs/{run_id}/events", headers={"Last-Event-ID": str(events[-1]["seq"] - 1)})
        )
        assert [event["seq"] for event in last_only] == [events[-1]["seq"]]
        assert model.calls == 2
        assert finished["usage"] == {
            "model_attempts": 2,
            "tool_executions": 1,
            "input_tokens": 20,
            "output_tokens": 10,
            "complete": True,
        }
        messages = client.get(f"/api/threads/{thread_id}/messages").json()["items"]
        assert len(messages) == 4 and len({message["id"] for message in messages}) == 4

        # 完成先赢时，晚到取消保持 succeeded，且不会写第二条终态事件。
        assert client.post(f"/api/runs/{run_id}/cancel").json()["status"] == "succeeded"
        all_events = _sse_events(client.get(f"/api/runs/{run_id}/events"))
        assert sum(event["type"] == "run.finished" for event in all_events) == 1
        with sqlite3.connect(tmp_path / "app.sqlite") as connection:
            assert connection.execute("SELECT COUNT(*) FROM runs WHERE id=?", (run_id,)).fetchone() == (1,)


def test_cancel_wins_and_late_model_completion_cannot_overwrite_it(tmp_path) -> None:
    model = BlockingOfflineModel()
    app = create_app(tmp_path, config=AppConfig(), model=model)
    with TestClient(app) as client:
        thread_id, run_id = _submit(client)
        assert model.started.wait(timeout=2)
        _wait_status(client, run_id, {"running"})

        cancel = client.post(f"/api/runs/{run_id}/cancel")
        assert cancel.status_code == 200 and cancel.json()["status"] in {"cancelling", "cancelled"}
        cancelled = _wait_status(client, run_id, {"cancelled"})
        model.release.set()
        time.sleep(0.05)

        assert client.get(f"/api/runs/{run_id}").json()["status"] == "cancelled"
        assert client.post(f"/api/runs/{run_id}/cancel").json()["status"] == "cancelled"
        assert cancelled["stop_reason"] == "user_cancelled"
        assert cancelled["usage"]["model_attempts"] == 1
        assert cancelled["usage"]["complete"] is False
        events = _sse_events(client.get(f"/api/runs/{run_id}/events"))
        terminal = [event for event in events if event["type"] == "run.finished"]
        assert len(terminal) == 1 and terminal[0]["data"]["status"] == "cancelled"
        messages = client.get(f"/api/threads/{thread_id}/messages").json()["items"]
        assert len(messages) == 1 and messages[0]["role"] == "user"


def test_model_failure_persists_failed_status_and_terminal_event(tmp_path) -> None:
    app = create_app(tmp_path, config=AppConfig(), model=FailingOfflineModel())
    with TestClient(app) as client:
        _, run_id = _submit(client)
        failed = _wait_status(client, run_id, {"failed"})
        assert failed["stop_reason"] == "error"
        assert failed["error"]["code"] == "AGENT_EXECUTION_FAILED"
        assert "planned model failure" in failed["error"]["message"]
        assert failed["usage"]["model_attempts"] == 1
        assert failed["usage"]["complete"] is False
        events = _sse_events(client.get(f"/api/runs/{run_id}/events"))
        assert events[-1]["type"] == "run.finished"
        assert events[-1]["data"]["status"] == "failed"


def test_tool_failure_is_not_converted_to_success(tmp_path) -> None:
    app = create_app(tmp_path, config=AppConfig(), model=OfflineChatModel(), tools=[failing_add])
    with TestClient(app) as client:
        _, run_id = _submit(client)
        failed = _wait_status(client, run_id, {"failed"})

        assert failed["stop_reason"] == "error"
        assert "planned tool failure" in failed["error"]["message"]
        assert failed["usage"]["model_attempts"] == 1
        assert failed["usage"]["tool_executions"] == 1
        events = _sse_events(client.get(f"/api/runs/{run_id}/events"))
        tool_events = [event for event in events if event["type"].startswith("tool.")]
        assert [event["type"] for event in tool_events] == ["tool.started", "tool.failed"]
        assert tool_events[1]["data"]["tool_call_id"] == "call-1"
        assert "planned tool failure" in tool_events[1]["data"]["error"]
        assert events[-1]["type"] == "run.finished"
        assert events[-1]["data"]["status"] == "failed"


def test_repeating_tool_calls_stop_within_configured_budgets(tmp_path) -> None:
    settings = AppConfig(
        runtime=RuntimeConfig(
            max_model_attempts_per_run=3,
            max_tool_executions_per_run=1,
        )
    )
    app = create_app(tmp_path, config=settings, model=RepeatingOfflineModel())
    with TestClient(app) as client:
        _, run_id = _submit(client)
        failed = _wait_status(client, run_id, {"failed"})

        assert "Model call limits exceeded" in failed["error"]["message"]
        assert failed["usage"]["model_attempts"] == 3
        # 第二、三次调用由 ToolCallLimitMiddleware 拦截，没有执行真实工具。
        assert failed["usage"]["tool_executions"] == 1
        assert _sse_events(client.get(f"/api/runs/{run_id}/events"))[-1]["data"]["status"] == "failed"
