import json
import shutil
import sqlite3
import subprocess
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from agentloom.api import create_app
from agentloom.config import AppConfig
from agentloom.models.fake import OfflineChatModel
from agentloom.sandbox import WorkspaceService


def _run(client: TestClient, text: str) -> tuple[str, str]:
    thread_id = client.post("/api/threads", json={}).json()["thread_id"]
    response = client.post(
        f"/api/threads/{thread_id}/runs",
        json={"text": text, "attachment_ids": [], "client_request_id": str(uuid4())},
    )
    run_id = response.json()["run_id"]
    for _ in range(300):
        if client.get(f"/api/runs/{run_id}").json()["status"] == "succeeded":
            return thread_id, run_id
        time.sleep(0.01)
    raise AssertionError("Run 未完成")


class PassingDocker:
    calls: list[dict]

    def __init__(self) -> None:
        self.calls = []

    async def execute_task(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(exit_code=0, stdout="1 passed\n", stderr="", truncated=False)


class FailingDocker(PassingDocker):
    async def execute_task(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(exit_code=1, stdout="", stderr="1 failed\n", truncated=False)


def _insert_coder_task(app_path, thread_id: str, run_id: str, task_id: str, *, content: str) -> None:
    now = "2026-01-01T00:00:00+00:00"
    result = {
        "task_id": task_id,
        "agent_type": "coder",
        "status": "succeeded",
        "summary": "完成",
        "artifact_ids": [],
        "sources": [],
        "task_files": ["/mnt/user-data/workspace/app.py"],
        "requires_parent_action": {"tool": "bash", "command": "pytest -q"},
        "acceptance": {"tests_passed": "unverified"},
        "error": None,
    }
    with sqlite3.connect(app_path) as connection:
        connection.execute(
            "INSERT INTO subagent_tasks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                task_id,
                run_id,
                f"call-{task_id}",
                "coder",
                "succeeded",
                "修改 app.py",
                json.dumps(result),
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
    task_file = app_path.parent / "threads" / thread_id / "tasks" / task_id / "workspace" / "app.py"
    task_file.parent.mkdir(parents=True, exist_ok=True)
    task_file.write_text(content, encoding="utf-8")


def test_safe_replay_reuses_only_terminal_tool_evidence_and_compares_runs(tmp_path) -> None:
    app = create_app(tmp_path, config=AppConfig(), model=OfflineChatModel())
    with TestClient(app) as client:
        _, first = _run(client, "请计算 2 + 3")
        _, second = _run(client, "普通回答")
        response = client.post(f"/api/runs/{first}/replays")
        assert response.status_code == 201
        replay = response.json()
        assert replay["evidence"]["will_execute_model"] is False
        assert replay["evidence"]["will_execute_tools"] is False
        assert replay["evidence"]["tool_evidence"][0]["reused_historical_result"] is True
        assert replay["evidence"]["tool_evidence"][0]["attempts"] == 1
        # 相同证据幂等复用同一回放，而不是制造第二次工具执行。
        assert client.post(f"/api/runs/{first}/replays").json()["replay_id"] == replay["replay_id"]
        comparison = client.get("/api/run-comparisons", params={"left_run_id": first, "right_run_id": second}).json()
        assert comparison["left"]["run_id"] == first
        assert comparison["delta"]["tool_sequence_changed"] is True
        # 故障注入未决账本；回放必须关闭，不能为了补结果再跑一次工具。
        with sqlite3.connect(tmp_path / "app.sqlite") as connection:
            connection.execute(
                "UPDATE tool_executions SET status='uncertain', result_json=NULL WHERE run_id=?", (first,)
            )
            connection.commit()
        blocked = client.post(f"/api/runs/{first}/replays")
        assert blocked.status_code == 409
        assert blocked.json()["error"]["code"] == "REPLAY_EVIDENCE_INCOMPLETE"


def test_coder_change_is_hash_bound_verified_and_atomically_accepted(tmp_path) -> None:
    app = create_app(tmp_path, config=AppConfig(), model=OfflineChatModel())
    docker = PassingDocker()
    with TestClient(app) as client:
        thread_id, run_id = _run(client, "普通回答")
        parent = tmp_path / "threads" / thread_id / "workspace" / "app.py"
        parent.write_text("print('old')\n", encoding="utf-8")
        task_id = str(uuid4())
        _insert_coder_task(tmp_path / "app.sqlite", thread_id, run_id, task_id, content="print('new')\n")
        client.app.state.coder_changes.docker = docker

        created = client.post(f"/api/subagents/{task_id}/change-proposals", json={})
        assert created.status_code == 201, created.text
        approval = created.json()["approval"]
        assert approval["kind"] == "coder_change"
        assert "-print('old')" in approval["payload"]["files"][0]["diff"]
        resolved = client.post(
            f"/api/approvals/{approval['approval_id']}/resolve",
            json={"payload_hash": approval["payload_hash"], "decision": "approve"},
        )
        assert resolved.status_code == 200, resolved.text
        assert resolved.json()["coder_change"]["status"] == "accepted"
        assert parent.read_text(encoding="utf-8") == "print('new')\n"
        assert docker.calls[0]["command"] == "pytest -q"
        with sqlite3.connect(tmp_path / "app.sqlite") as connection:
            acceptance = json.loads(
                connection.execute("SELECT acceptance_json FROM subagent_tasks WHERE id=?", (task_id,)).fetchone()[0]
            )
        assert acceptance["tests_passed"] is True
        assert acceptance["docker"]["exit_code"] == 0
        # 重复批准复用同一审批与接纳结果，不能再次启动验证容器。
        repeated = client.post(
            f"/api/approvals/{approval['approval_id']}/resolve",
            json={"payload_hash": approval["payload_hash"], "decision": "approve"},
        )
        assert repeated.json()["coder_change"]["status"] == "accepted"
        assert len(docker.calls) == 1


def test_coder_change_refuses_stale_parent_hash_after_docker_passes(tmp_path) -> None:
    app = create_app(tmp_path, config=AppConfig(), model=OfflineChatModel())
    with TestClient(app) as client:
        thread_id, run_id = _run(client, "普通回答")
        parent = tmp_path / "threads" / thread_id / "workspace" / "app.py"
        parent.write_text("base\n", encoding="utf-8")
        task_id = str(uuid4())
        _insert_coder_task(tmp_path / "app.sqlite", thread_id, run_id, task_id, content="coder\n")
        client.app.state.coder_changes.docker = PassingDocker()
        approval = client.post(f"/api/subagents/{task_id}/change-proposals", json={}).json()["approval"]
        parent.write_text("human edit\n", encoding="utf-8")
        response = client.post(
            f"/api/approvals/{approval['approval_id']}/resolve",
            json={"payload_hash": approval["payload_hash"], "decision": "approve"},
        )
        assert response.status_code == 200
        assert response.json()["coder_change"]["status"] == "conflict"
        assert parent.read_text(encoding="utf-8") == "human edit\n"


def test_coder_change_keeps_parent_untouched_when_docker_fails(tmp_path) -> None:
    app = create_app(tmp_path, config=AppConfig(), model=OfflineChatModel())
    with TestClient(app) as client:
        thread_id, run_id = _run(client, "普通回答")
        parent = tmp_path / "threads" / thread_id / "workspace" / "app.py"
        parent.write_text("base\n", encoding="utf-8")
        task_id = str(uuid4())
        _insert_coder_task(tmp_path / "app.sqlite", thread_id, run_id, task_id, content="broken\n")
        client.app.state.coder_changes.docker = FailingDocker()
        approval = client.post(f"/api/subagents/{task_id}/change-proposals", json={}).json()["approval"]
        response = client.post(
            f"/api/approvals/{approval['approval_id']}/resolve",
            json={"payload_hash": approval["payload_hash"], "decision": "approve"},
        )
        change = response.json()["coder_change"]
        assert change["status"] == "failed"
        assert change["verification"]["exit_code"] == 1
        assert parent.read_text(encoding="utf-8") == "base\n"


def test_atomic_file_set_rolls_back_files_published_before_failure(tmp_path, monkeypatch) -> None:
    workspace = WorkspaceService(tmp_path / "threads")
    thread_id = str(uuid4())
    first = workspace.write_text(thread_id, "/mnt/user-data/workspace/a.txt", "old-a")
    second = workspace.write_text(thread_id, "/mnt/user-data/workspace/b.txt", "old-b")
    from agentloom.sandbox import workspace as workspace_module

    original_replace = workspace_module.os.replace
    calls = 0

    def fail_second_publish(source, target):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected second publish failure")
        return original_replace(source, target)

    monkeypatch.setattr(workspace_module.os, "replace", fail_second_publish)
    with pytest.raises(OSError, match="injected"):
        workspace.apply_file_set(
            thread_id,
            [
                {"path": first.virtual_path, "base_sha256": first.sha256, "content": b"new-a"},
                {"path": second.virtual_path, "base_sha256": second.sha256, "content": b"new-b"},
            ],
        )
    assert workspace.read_text(thread_id, first.virtual_path).content == "old-a"
    assert workspace.read_text(thread_id, second.virtual_path).content == "old-b"


@pytest.mark.docker
def test_real_docker_verifies_coder_workspace_before_acceptance(tmp_path) -> None:
    executable = shutil.which("docker")
    if executable is None:
        pytest.skip("本机没有 docker 命令")
    inspected = subprocess.run(
        [executable, "image", "inspect", "agentloom-python:v1"], capture_output=True, check=False
    )
    if inspected.returncode != 0:
        pytest.skip("缺少镜像 agentloom-python:v1；先按 README 构建")

    app = create_app(tmp_path, config=AppConfig(), model=OfflineChatModel())
    with TestClient(app) as client:
        thread_id, run_id = _run(client, "普通回答")
        task_id = str(uuid4())
        _insert_coder_task(
            tmp_path / "app.sqlite",
            thread_id,
            run_id,
            task_id,
            content="def add(a, b):\n    return a + b\n",
        )
        task_root = tmp_path / "threads" / thread_id / "tasks" / task_id / "workspace"
        (task_root / "test_calc.py").write_text(
            "from app import add\n\ndef test_add():\n    assert add(2, 3) == 5\n", encoding="utf-8"
        )
        created = client.post(
            f"/api/subagents/{task_id}/change-proposals",
            json={"verification_command": "pytest -q -p no:cacheprovider"},
        ).json()
        approval = created["approval"]
        resolved = client.post(
            f"/api/approvals/{approval['approval_id']}/resolve",
            json={"payload_hash": approval["payload_hash"], "decision": "approve"},
        )
        change = resolved.json()["coder_change"]
        assert change["status"] == "accepted", json.dumps(change, ensure_ascii=False)
        assert change["verification"]["exit_code"] == 0
        assert "1 passed" in change["verification"]["stdout"]
        parent_root = tmp_path / "threads" / thread_id / "workspace"
        assert (parent_root / "app.py").is_file()
        assert (parent_root / "test_calc.py").is_file()
