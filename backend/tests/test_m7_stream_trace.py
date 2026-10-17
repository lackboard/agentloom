import asyncio
import json
import sqlite3
import threading
import time
from uuid import uuid4

from fastapi.testclient import TestClient
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import PrivateAttr

from agentloom.api import create_app
from agentloom.config import AppConfig
from agentloom.models.fake import OfflineChatModel


class SlowStreamingModel(BaseChatModel):
    """首段输出后暂停，证明增量在模型结束前已经持久化。"""

    _first_chunk: threading.Event = PrivateAttr(default_factory=threading.Event)
    _release: threading.Event = PrivateAttr(default_factory=threading.Event)

    @property
    def _llm_type(self) -> str:
        return "agentloom-test-stream"

    @property
    def first_chunk(self) -> threading.Event:
        return self._first_chunk

    @property
    def release(self) -> threading.Event:
        return self._release

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=AIMessage(id="stream-answer", content="第一段第二段"))])

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        yield ChatGenerationChunk(message=AIMessageChunk(id="stream-answer", content="第一段"))
        self._first_chunk.set()
        while not self._release.is_set():
            await asyncio.sleep(0.01)
        yield ChatGenerationChunk(
            message=AIMessageChunk(
                id="stream-answer",
                content="第二段",
                usage_metadata={"input_tokens": 7, "output_tokens": 4, "total_tokens": 11},
            )
        )


class FailingStreamingModel(SlowStreamingModel):
    """模型在产生任何可见输出前失败，用于验证失败 Trace 收口。"""

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        if False:  # pragma: no cover - 保持此函数是异步生成器。
            yield
        raise RuntimeError("injected stream failure")


def _submit(client: TestClient, text: str) -> tuple[str, str]:
    thread_id = client.post("/api/threads", json={}).json()["thread_id"]
    response = client.post(
        f"/api/threads/{thread_id}/runs",
        json={"text": text, "attachment_ids": [], "client_request_id": str(uuid4())},
    )
    assert response.status_code == 202
    return thread_id, response.json()["run_id"]


def _wait_status(client: TestClient, run_id: str, expected: str) -> dict:
    for _ in range(300):
        result = client.get(f"/api/runs/{run_id}").json()
        if result["status"] == expected:
            return result
        time.sleep(0.01)
    raise AssertionError(f"Run 没有进入 {expected}，最后状态为 {result['status']}")


def test_stream_delta_is_durable_before_completion_and_trace_forms_tree(tmp_path) -> None:
    model = SlowStreamingModel()
    app = create_app(tmp_path, config=AppConfig(), model=model)
    with TestClient(app) as client:
        thread_id, run_id = _submit(client, "请流式回答")
        assert model.first_chunk.wait(timeout=2)

        # 定时批处理窗口为 50ms；模型仍被阻塞时数据库中必须已出现增量。
        deadline = time.time() + 2
        delta_rows = []
        while time.time() < deadline:
            with sqlite3.connect(tmp_path / "app.sqlite") as connection:
                delta_rows = connection.execute(
                    "SELECT payload_json FROM run_events WHERE run_id=? AND event_type='message.delta' ORDER BY seq",
                    (run_id,),
                ).fetchall()
            if delta_rows:
                break
            time.sleep(0.01)
        assert json.loads(delta_rows[0][0])["delta"] == "第一段"
        assert client.get(f"/api/runs/{run_id}").json()["status"] == "running"

        running_trace = client.get(f"/api/runs/{run_id}/trace").json()
        assert running_trace["trace_id"]
        assert [span["kind"] for span in running_trace["spans"]] == ["run", "model"]
        assert running_trace["spans"][1]["parent_span_id"] == running_trace["root_span_id"]

        model.release.set()
        detail = _wait_status(client, run_id, "succeeded")
        assert detail["trace_id"] == running_trace["trace_id"]
        messages = client.get(f"/api/threads/{thread_id}/messages").json()["items"]
        answer = next(message for message in messages if message["role"] == "assistant")
        assert answer["id"] == "stream-answer"
        assert answer["content"]["text"] == "第一段第二段"
        assert answer["status"] == "completed"

        with sqlite3.connect(tmp_path / "app.sqlite") as connection:
            events = connection.execute(
                "SELECT event_type,payload_json FROM run_events WHERE run_id=? ORDER BY seq", (run_id,)
            ).fetchall()
        deltas = [json.loads(payload)["delta"] for event_type, payload in events if event_type == "message.delta"]
        completed = [json.loads(payload) for event_type, payload in events if event_type == "message.completed"]
        assert "".join(deltas) == "第一段第二段"
        assert sum(item.get("message_id") == "stream-answer" for item in completed) == 1

        trace = client.get(f"/api/runs/{run_id}/trace").json()
        root, model_span = trace["spans"]
        assert root["status"] == model_span["status"] == "succeeded"
        assert root["duration_ms"] is not None and model_span["duration_ms"] is not None
        assert model_span["attributes"] == {
            "attempt": 1,
            "input_tokens": 7,
            "output_tokens": 4,
            "usage_reported": True,
        }
        assert "第一段" not in json.dumps(trace, ensure_ascii=False)


def test_tool_trace_records_structure_without_arguments_or_result(tmp_path) -> None:
    app = create_app(tmp_path, config=AppConfig(), model=OfflineChatModel())
    with TestClient(app) as client:
        _, run_id = _submit(client, "请计算 2 + 3")
        _wait_status(client, run_id, "succeeded")
        trace = client.get(f"/api/runs/{run_id}/trace").json()

    kinds = [span["kind"] for span in trace["spans"]]
    assert kinds.count("run") == 1
    assert kinds.count("model") == 2
    assert kinds.count("tool") == 1
    model_spans = [span for span in trace["spans"] if span["kind"] == "model"]
    assert all(span["parent_span_id"] == trace["root_span_id"] for span in model_spans)
    tool_span = next(span for span in trace["spans"] if span["kind"] == "tool")
    assert tool_span["parent_span_id"] == model_spans[0]["span_id"]
    assert tool_span["name"] == "add"
    assert set(tool_span["attributes"]) == {"tool_call_id"}
    assert '"a"' not in json.dumps(tool_span) and "最终答案" not in json.dumps(tool_span, ensure_ascii=False)


def test_stream_failure_closes_model_and_root_spans(tmp_path) -> None:
    app = create_app(tmp_path, config=AppConfig(), model=FailingStreamingModel())
    with TestClient(app) as client:
        _, run_id = _submit(client, "触发流式失败")
        detail = _wait_status(client, run_id, "failed")
        trace = client.get(f"/api/runs/{run_id}/trace").json()

    assert detail["error"]["code"] == "AGENT_EXECUTION_FAILED"
    root, model_span = trace["spans"]
    assert root["status"] == model_span["status"] == "failed"
    assert root["error_code"] == "AGENT_EXECUTION_FAILED"
    assert model_span["error_code"] == "RuntimeError"
    assert all(span["finished_at"] and span["duration_ms"] is not None for span in trace["spans"])
