"""M7.5 确定性故障注入演示：失败可见、写操作不盲重放、接纳失败不污染父目录。"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import time
from dataclasses import asdict, dataclass, field
from functools import partial
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

from agentloom.api import create_app
from agentloom.config import AppConfig
from agentloom.models.fake import OfflineChatModel


@dataclass(frozen=True)
class Check:
    """一条可机器判断的演示断言。"""

    name: str
    passed: bool
    observed: object
    expected: object


@dataclass
class Scenario:
    """一个故障点的输入、观察结果和不变量。"""

    name: str
    fault: str
    checks: list[Check] = field(default_factory=list)
    evidence: dict = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    def check(self, name: str, observed: object, expected: object) -> None:
        self.checks.append(Check(name, observed == expected, observed, expected))


class FailingStreamingModel(BaseChatModel):
    """在首个可见增量前抛错，稳定复现模型流中断。"""

    @property
    def _llm_type(self) -> str:
        return "agentloom-m7-fault-stream"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="不会到达这里"))])

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        if False:  # pragma: no cover - 让函数保持异步生成器协议。
            yield ChatGenerationChunk(message=AIMessageChunk(content=""))
        raise RuntimeError("M7_FAULT_MODEL_STREAM")


class FailingDocker:
    """只替换 Docker 依赖，返回真实失败形状而不执行宿主机命令。"""

    def __init__(self) -> None:
        self.calls = 0

    async def execute_task(self, **kwargs):
        self.calls += 1
        return SimpleNamespace(exit_code=1, stdout="", stderr="1 failed\n", truncated=False)


def _submit(client: TestClient, text: str) -> tuple[str, str]:
    thread_id = client.post("/api/threads", json={}).json()["thread_id"]
    response = client.post(
        f"/api/threads/{thread_id}/runs",
        json={"text": text, "attachment_ids": [], "client_request_id": str(uuid4())},
    )
    response.raise_for_status()
    return thread_id, response.json()["run_id"]


def _wait_terminal(client: TestClient, run_id: str) -> dict:
    result: dict = {}
    for _ in range(500):
        result = client.get(f"/api/runs/{run_id}").json()
        if result.get("status") in {"succeeded", "failed", "cancelled"}:
            return result
        time.sleep(0.01)
    raise TimeoutError(f"Run 未进入终态：{result}")


def _model_stream_failure(root: Path) -> Scenario:
    scenario = Scenario("model_stream_failure", "首个模型增量前抛出 RuntimeError")
    with TestClient(create_app(root, config=AppConfig(), model=FailingStreamingModel())) as client:
        _, run_id = _submit(client, "触发模型流故障")
        run = _wait_terminal(client, run_id)
        trace = client.get(f"/api/runs/{run_id}/trace").json()
        spans = trace["spans"]
        scenario.check("run_failed", run["status"], "failed")
        scenario.check("stable_error_code", run["error"]["code"], "AGENT_EXECUTION_FAILED")
        scenario.check("all_spans_closed", all(span["finished_at"] for span in spans), True)
        scenario.check("model_error_visible", spans[-1]["error_code"], "RuntimeError")
        scenario.evidence = {
            "run_id": run_id,
            "trace_id": trace["trace_id"],
            "span_statuses": [f"{span['kind']}:{span['status']}" for span in spans],
        }
    return scenario


def _uncertain_write_recovery(root: Path) -> Scenario:
    scenario = Scenario("uncertain_write_recovery", "文件已写入，但 write_file 账本仍停在 running 后重启")
    virtual_path = "/mnt/user-data/outputs/recovery.txt"
    run_id = ""
    execution_id = ""
    expected_sha = ""

    # 第一段模拟进程在副作用发生后、ledger.finish() 前退出。没有调用生产代码中的故障开关。
    app = create_app(root, config=AppConfig(), model=OfflineChatModel())
    with TestClient(app) as client:
        thread_id = client.post("/api/threads", json={}).json()["thread_id"]
        run = client.portal.call(
            partial(
                app.state.manager.submit,
                thread_id,
                text="模拟写工具执行到一半",
                client_request_id=str(uuid4()),
            )
        )
        run_id = run.id
        started = client.portal.call(app.state.manager.try_start, run_id)
        record = client.portal.call(
            partial(
                app.state.ledger.prepare,
                run_id,
                "fault-write-1",
                "write_file",
                {"path": virtual_path, "content": "only-once"},
                replay_class="idempotent",
                precondition={"evidence_paths": [virtual_path]},
            )
        )
        execution_id = record.id
        client.portal.call(app.state.ledger.begin, execution_id)
        written = app.state.workspace.write_text(thread_id, virtual_path, "only-once")
        expected_sha = written.sha256
        scenario.check("run_started", started, True)

    # 第二次启动执行启动对账：running 工具转 uncertain，所属 running Run 转 interrupted。
    restarted = create_app(root, config=AppConfig(), model=OfflineChatModel())
    with TestClient(restarted) as client:
        run = client.get(f"/api/runs/{run_id}").json()
        ledger = client.get(f"/api/runs/{run_id}/tool-executions").json()["items"][0]
        blocked = client.post(f"/api/runs/{run_id}/recover")
        replay = client.post(f"/api/runs/{run_id}/replays")
        content = restarted.state.workspace.read_text(run["thread_id"], virtual_path)

        scenario.check("run_interrupted", run["status"], "interrupted")
        scenario.check("ledger_uncertain", ledger["status"], "uncertain")
        scenario.check("execution_attempted_once", ledger["attempts"], 1)
        scenario.check("automatic_recovery_blocked", blocked.status_code, 409)
        scenario.check("historical_replay_blocked", replay.status_code, 409)
        scenario.check("replay_error_visible", replay.json()["error"]["code"], "REPLAY_EVIDENCE_INCOMPLETE")
        scenario.check("side_effect_hash_preserved", content.sha256, expected_sha)

        verified = client.post(
            f"/api/tool-executions/{execution_id}/resolve",
            json={"action": "verify", "evidence": [{"path": virtual_path, "sha256": expected_sha}]},
        )
        scenario.check("evidence_verification_accepted", verified.status_code, 200)
        after = client.get(f"/api/runs/{run_id}/tool-executions").json()["items"][0]
        scenario.check("verification_did_not_reexecute", after["attempts"], 1)
        scenario.check("verified_result_terminal", after["status"], "succeeded")
        scenario.evidence = {
            "run_id": run_id,
            "execution_id": execution_id,
            "file_sha256": expected_sha,
            "recovery_error": blocked.json()["error"]["code"],
            "replay_error": replay.json()["error"]["code"],
            "final_ledger_status": after["status"],
        }
    return scenario


def _insert_finished_coder_task(db_path: Path, thread_id: str, run_id: str, task_id: str) -> None:
    """建立已结束 Coder 记录；故障演示聚焦后续验证/接纳边界。"""

    now = "2026-01-01T00:00:00+00:00"
    result = {
        "task_id": task_id,
        "agent_type": "coder",
        "status": "succeeded",
        "summary": "已生成候选修改",
        "artifact_ids": [],
        "sources": [],
        "task_files": ["/mnt/user-data/workspace/app.py"],
        "requires_parent_action": {"tool": "bash", "command": "pytest -q"},
        "acceptance": {"tests_passed": "unverified"},
        "error": None,
    }
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "INSERT INTO subagent_tasks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                task_id,
                run_id,
                f"call-{task_id}",
                "coder",
                "succeeded",
                "修改 app.py",
                json.dumps(result, ensure_ascii=False),
                json.dumps({"tests_passed": "unverified"}),
                0,
                0,
                1,
                now,
                now,
                now,
                "2099-01-01T00:00:00+00:00",
            ),
        )
        connection.commit()


def _coder_validation_failure(root: Path) -> Scenario:
    scenario = Scenario("coder_validation_failure", "Docker 验证返回退出码 1")
    docker = FailingDocker()
    app = create_app(root, config=AppConfig(), model=OfflineChatModel())
    with TestClient(app) as client:
        thread_id, run_id = _submit(client, "请计算 2 + 3")
        completed = _wait_terminal(client, run_id)
        scenario.check("source_run_succeeded", completed["status"], "succeeded")

        parent = root / "threads" / thread_id / "workspace" / "app.py"
        parent.write_text("base\n", encoding="utf-8")
        expected_parent_hash = hashlib.sha256(parent.read_bytes()).hexdigest()
        task_id = str(uuid4())
        _insert_finished_coder_task(root / "app.sqlite", thread_id, run_id, task_id)
        task_file = root / "threads" / thread_id / "tasks" / task_id / "workspace" / "app.py"
        task_file.parent.mkdir(parents=True, exist_ok=True)
        task_file.write_text("broken candidate\n", encoding="utf-8")
        app.state.coder_changes.docker = docker

        created = client.post(f"/api/subagents/{task_id}/change-proposals", json={})
        created.raise_for_status()
        approval = created.json()["approval"]
        resolved = client.post(
            f"/api/approvals/{approval['approval_id']}/resolve",
            json={"payload_hash": approval["payload_hash"], "decision": "approve"},
        )
        resolved.raise_for_status()
        change = resolved.json()["coder_change"]
        scenario.check("proposal_failed", change["status"], "failed")
        scenario.check("docker_exit_visible", change["verification"]["exit_code"], 1)
        scenario.check("docker_called_once", docker.calls, 1)
        parent_hash = hashlib.sha256(parent.read_bytes()).hexdigest()
        scenario.check("parent_hash_unchanged", parent_hash, expected_parent_hash)
        scenario.evidence = {
            "run_id": run_id,
            "task_id": task_id,
            "proposal_id": change["proposal_id"],
            "error_code": change["error"]["code"],
        }
    return scenario


def _markdown(report: dict) -> str:
    lines = [
        "# AgentLoom M7.5 故障注入报告",
        "",
        f"- 模式：`{report['mode']}`",
        f"- 总结果：`{'PASS' if report['passed'] else 'FAIL'}`",
        f"- 场景数：{len(report['scenarios'])}",
        "",
    ]
    for scenario in report["scenarios"]:
        lines.extend([f"## {scenario['name']}", "", f"注入点：{scenario['fault']}", ""])
        for check in scenario["checks"]:
            mark = "PASS" if check["passed"] else "FAIL"
            lines.append(f"- `{mark}` {check['name']}: observed={check['observed']!r}")
        lines.append("")
    return "\n".join(lines)


def run_demo(output: Path) -> dict:
    output.parent.mkdir(parents=True, exist_ok=True)
    # 临时业务库放在输出目录所在磁盘，避免默认系统临时目录占用 C 盘。
    with TemporaryDirectory(prefix=".m7-fault-", dir=output.parent) as directory:
        root = Path(directory)
        scenarios = [
            _model_stream_failure(root / "model"),
            _uncertain_write_recovery(root / "uncertain"),
            _coder_validation_failure(root / "coder"),
        ]
    report = {
        "schema_version": 1,
        "mode": "deterministic_fault_injection_fake",
        "passed": all(scenario.passed for scenario in scenarios),
        "scenarios": [{**asdict(scenario), "passed": scenario.passed} for scenario in scenarios],
        "limitations": [
            "该报告验证 AgentLoom 的失败语义，不代表真实模型供应商发生过同样故障。",
            "当前未实现跨模型自动故障切换；provider 自身重试由配置的 SDK 负责。",
        ],
    }
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    output.with_suffix(".md").write_text(_markdown(report), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="运行 AgentLoom M7.5 确定性故障注入演示")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "output" / "m7-fault-demo" / "report.json",
        help="JSON 报告路径；同目录同时生成 Markdown 报告",
    )
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    report = run_demo(args.output.resolve())
    for scenario in report["scenarios"]:
        print(f"{scenario['name']}: {'PASS' if scenario['passed'] else 'FAIL'}")
        for check in scenario["checks"]:
            if not check["passed"]:
                print(f"  {check['name']}: observed={check['observed']!r}, expected={check['expected']!r}")
    print(f"report: {args.output.resolve()}")
    print(f"M7 FAULT DEMO: {'PASS' if report['passed'] else 'FAIL'}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
