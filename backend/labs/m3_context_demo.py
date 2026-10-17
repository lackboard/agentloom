"""M3.3～M3.4：观察大结果外置、摘要计量和 UI 历史保留。"""

import json
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import StructuredTool
from pydantic import PrivateAttr

from agentloom.api import create_app
from agentloom.config import AppConfig, ContextConfig, ModelConfig, ModelsConfig


def large_result(label: str) -> str:
    """返回足够大的确定性文本，确保触发结果外置。"""
    return f"{label}|" + label * 2500


LARGE_TOOL = StructuredTool.from_function(
    func=large_result,
    name="large_result",
    description="生成一段确定性的大文本。",
)


class DemoModel(BaseChatModel):
    """固定执行四次工具；摘要请求和正式请求走同一个模型对象。"""

    _workflow_calls: int = PrivateAttr(default=0)
    _summary_calls: int = PrivateAttr(default=0)

    @property
    def _llm_type(self) -> str:
        return "m3-context-demo"

    @property
    def summary_calls(self) -> int:
        return self._summary_calls

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages: list[AnyMessage], stop=None, run_manager=None, **kwargs) -> ChatResult:
        is_summary = any(
            isinstance(message, HumanMessage)
            and isinstance(message.content, str)
            and message.content.startswith("你是 Agent 上下文压缩器")
            for message in messages
        )
        if is_summary:
            self._summary_calls += 1
            answer = AIMessage(
                content="摘要：早期步骤已完成，完整内容保存在 tool-results 引用中。",
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


def wait_for_finish(client: TestClient, run_id: str) -> dict:
    for _ in range(400):
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] in {"succeeded", "failed", "cancelled"}:
            return run
        time.sleep(0.01)
    raise RuntimeError(f"Run 未在预期时间内结束：{run_id}")


def main() -> None:
    model = DemoModel()
    config = AppConfig(
        models=ModelsConfig(default=ModelConfig(context_window=1800, max_output_tokens=100)),
        context=ContextConfig(compaction_fraction=0.40, tool_preview_bytes=256),
    )
    with tempfile.TemporaryDirectory(prefix="agentloom-m3-") as directory:
        data_dir = Path(directory)
        app = create_app(data_dir, config=config, model=model, tools=[LARGE_TOOL])
        with TestClient(app) as client:
            thread_id = client.post("/api/threads", json={}).json()["thread_id"]
            response = client.post(
                f"/api/threads/{thread_id}/runs",
                json={
                    "text": "连续执行四个大结果步骤",
                    "attachment_ids": [],
                    "client_request_id": str(uuid4()),
                },
            )
            run_id = response.json()["run_id"]
            run = wait_for_finish(client, run_id)
            messages = client.get(f"/api/threads/{thread_id}/messages").json()["items"]

        tool_messages = [item for item in messages if item["role"] == "tool"]
        first_reference = json.loads(tool_messages[0]["content"]["text"])
        stored = list((data_dir / "threads" / thread_id / "tool-results" / run_id).glob("*.txt"))
        print("Run 状态：", run["status"])
        print("摘要调用次数：", model.summary_calls)
        print("总模型尝试次数：", run["usage"]["model_attempts"])
        print("UI 历史角色：", [item["role"] for item in messages])
        print("模型收到的预览字节：", len(first_reference["preview"].encode("utf-8")))
        print("完整结果引用：", first_reference["full_result_path"])
        print("只读结果文件数：", len(stored))

        assert run["status"] == "succeeded"
        assert model.summary_calls >= 1
        assert len(tool_messages) == len(stored) == 4
        assert len(first_reference["preview"].encode("utf-8")) <= 256
        print("M3.3/M3.4 DEMO: PASS")


if __name__ == "__main__":
    main()
