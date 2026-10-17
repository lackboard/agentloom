"""M5 浏览器验收服务：真实执行链配可预测模型，避免消耗 API key。"""

import csv
import io
import json
import os
import re
from collections.abc import Sequence
from pathlib import Path

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from agentloom.api import create_app
from agentloom.config import AppConfig

VIRTUAL_PATH = re.compile(r'"virtual_path"\s*:\s*"([^"]+)"')


class UiDemoModel(BaseChatModel):
    """按“读 CSV → 新建草稿 → 审批替换 → 展示产物”推进。"""

    @property
    def _llm_type(self) -> str:
        return "agentloom-m5-ui-demo"

    def bind_tools(self, tools, **kwargs):
        return self

    @staticmethod
    def _call(name: str, args: dict, call_id: str) -> AIMessage:
        return AIMessage(
            content="",
            tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}],
            usage_metadata={"input_tokens": 12, "output_tokens": 8, "total_tokens": 20},
        )

    def _generate(self, messages: list[AnyMessage], stop=None, run_manager=None, **kwargs) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._respond(messages))])

    def _respond(self, messages: Sequence[AnyMessage]) -> AIMessage:
        last = messages[-1]
        if isinstance(last, HumanMessage):
            match = VIRTUAL_PATH.search(str(last.content))
            if match is None:
                return AIMessage(content="请先上传一个 CSV 文件。")
            return self._call("read_file", {"path": match.group(1), "max_chars": 512}, "ui-read")

        if not isinstance(last, ToolMessage):
            return AIMessage(content="演示流程收到未知消息。")
        result = json.loads(str(last.content))
        if last.name == "read_file":
            rows = list(csv.DictReader(io.StringIO(str(result.get("content", "")))))
            numeric = []
            for row in rows:
                for value in row.values():
                    try:
                        numeric.append(float(value))
                    except (TypeError, ValueError):
                        continue
            total = sum(numeric)
            draft = f"# 数据分析报告\n\n待确认结论\n\n- 记录数：{len(rows)}\n- 数值合计：{total:g}\n"
            return self._call("write_file", {"path": "/mnt/user-data/outputs/report.md", "content": draft}, "ui-write")
        if last.name == "write_file":
            return self._call(
                "replace_file",
                {
                    "path": "/mnt/user-data/outputs/report.md",
                    "old": "待确认结论",
                    "new": "## 已确认结论\n\n数据已读取并完成聚合，以下结果可用于后续核验。",
                    "expected_sha256": result["sha256"],
                },
                "ui-approve-replace",
            )
        if last.name == "replace_file":
            return self._call("present_files", {"filepaths": ["/mnt/user-data/outputs/report.md"]}, "ui-present")
        if last.name == "present_files":
            return AIMessage(
                content="分析完成，右侧文件面板中的 `report.md` 是经过审批后登记的不可变产物。",
                usage_metadata={"input_tokens": 10, "output_tokens": 12, "total_tokens": 22},
            )
        return AIMessage(content=f"工具 {last.name} 返回：{last.content}")


data_dir = Path(os.environ.get("AGENTLOOM_UI_DEMO_DATA", ".agentloom/m5-ui-demo"))
app = create_app(data_dir=data_dir, config=AppConfig(), model=UiDemoModel())
