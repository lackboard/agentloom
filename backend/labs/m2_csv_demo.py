"""M2.6：上传 CSV，经审批在 Docker 中生成 Markdown/PNG，再登记下载。"""

import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agentloom.api import create_app
from agentloom.config import AppConfig
from agentloom.models.fake import OfflineChatModel

ANALYSIS_SCRIPT = """\
from pathlib import Path
import glob
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

source = glob.glob("/mnt/user-data/uploads/*/*.csv")[0]
frame = pd.read_csv(source)
summary = frame.groupby("category", as_index=False)["value"].sum()
outputs = Path("/mnt/user-data/outputs")
outputs.mkdir(parents=True, exist_ok=True)
summary.to_markdown(outputs / "report.md", index=False)
summary.plot.bar(x="category", y="value", legend=False, title="Value by category")
plt.tight_layout()
plt.savefig(outputs / "chart.png")
"""


class CsvDemoModel(OfflineChatModel):
    """确定性提出真实文件与 Docker 工具调用；结果仍来自工具，不伪造完成。"""

    def _respond(self, messages):
        if not any(isinstance(item, HumanMessage) for item in messages):
            raise TypeError("演示需要用户输入")
        finished_tools = {item.name for item in messages if isinstance(item, ToolMessage)}
        if "write_file" not in finished_tools:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "write_file",
                        "args": {"path": "/mnt/user-data/workspace/analyze.py", "content": ANALYSIS_SCRIPT},
                        "id": "csv-write-script",
                        "type": "tool_call",
                    }
                ],
                usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            )
        if "bash" not in finished_tools:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "bash",
                        "args": {
                            "command": "python /mnt/user-data/workspace/analyze.py",
                            "evidence_paths": [
                                "/mnt/user-data/outputs/report.md",
                                "/mnt/user-data/outputs/chart.png",
                            ],
                        },
                        "id": "csv-run-analysis",
                        "type": "tool_call",
                    }
                ],
                usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            )
        if "present_files" not in finished_tools:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "present_files",
                        "args": {
                            "filepaths": [
                                "/mnt/user-data/outputs/report.md",
                                "/mnt/user-data/outputs/chart.png",
                            ]
                        },
                        "id": "csv-present-results",
                        "type": "tool_call",
                    }
                ],
                usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            )
        return AIMessage(
            content="CSV 分析已完成并登记两个产物。",
            usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        )


def wait_status(client: TestClient, run_id: str, expected: set[str]) -> dict:
    for _ in range(600):
        result = client.get(f"/api/runs/{run_id}").json()
        if result["status"] in expected:
            return result
        time.sleep(0.05)
    raise RuntimeError(f"Run 未进入 {expected}：{result}")


def main() -> int:
    docker = shutil.which("docker")
    image = "agentloom-python:v1"
    if docker is None:
        print("M2.6 CSV DEMO: NOT_RUN - 本机没有 docker 命令")
        return 0
    inspected = subprocess.run([docker, "image", "inspect", image], capture_output=True, check=False)
    if inspected.returncode != 0:
        print(f"M2.6 CSV DEMO: NOT_RUN - 缺少镜像 {image}")
        print("build: docker build -t agentloom-python:v1 -f docker/Dockerfile docker")
        return 0

    with tempfile.TemporaryDirectory(prefix="agentloom-m2-csv-") as directory:
        app = create_app(Path(directory), config=AppConfig(), model=CsvDemoModel())
        with TestClient(app) as client:
            thread_id = client.post("/api/threads", json={}).json()["thread_id"]
            upload = client.post(
                f"/api/threads/{thread_id}/uploads",
                files={"file": ("sales.csv", b"category,value\nA,2\nB,3\nA,5\n", "text/csv")},
            ).json()
            run_id = client.post(
                f"/api/threads/{thread_id}/runs",
                json={
                    "text": f"分析上传的 CSV：{upload['virtual_path']}",
                    "attachment_ids": [],
                    "client_request_id": str(uuid4()),
                },
            ).json()["run_id"]
            waiting = wait_status(client, run_id, {"waiting_input", "failed"})
            if waiting["status"] == "failed":
                raise RuntimeError(waiting["error"])
            approval = client.get(f"/api/runs/{run_id}/approvals").json()["items"][0]
            client.post(
                f"/api/approvals/{approval['approval_id']}/resolve",
                json={"payload_hash": approval["payload_hash"], "decision": "approve", "reason": "运行 CSV 演示"},
            ).raise_for_status()
            completed = wait_status(client, run_id, {"succeeded", "failed"})
            if completed["status"] != "succeeded":
                raise RuntimeError(completed["error"])
            messages = client.get(f"/api/threads/{thread_id}/messages").json()["items"]
            presented = next(
                item for item in messages if item["role"] == "tool" and item["content"].get("name") == "present_files"
            )
            artifact_ids = [item["id"] for item in __import__("json").loads(presented["content"]["text"])["artifacts"]]
            downloads = [client.get(f"/api/artifacts/{artifact_id}/content") for artifact_id in artifact_ids]
            assert all(response.status_code == 200 and response.content for response in downloads)
            assert any(
                response.content.startswith(b"\x89PNG\r\n\x1a\n")
                and response.content.endswith(b"\x00\x00\x00\x00IEND\xaeB`\x82")
                for response in downloads
            ), "没有下载到结构完整的 PNG 图表"
            assert any(b"category" in response.content and b"value" in response.content for response in downloads), (
                "没有下载到包含聚合字段的 Markdown 报告"
            )
            print(f"upload: {upload['artifact_id']} {upload['sha256']}")
            print(f"run: {run_id} status={completed['status']}")
            print(f"artifacts: {artifact_ids}")
            print("M2.6 CSV DEMO: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
