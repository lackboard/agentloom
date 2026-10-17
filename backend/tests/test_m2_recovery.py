import asyncio
import hashlib
import json
import shutil
import subprocess
import threading
import time
from functools import partial
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agentloom.api import create_app
from agentloom.config import AppConfig, SandboxConfig
from agentloom.models.fake import OfflineChatModel
from agentloom.sandbox import DockerCommandResult, DockerCommandService, DockerCommandTimeout


class BashBatchModel(OfflineChatModel):
    """先提出 Bash 与普通写文件，读取整批结果后结束。"""

    def _respond(self, messages):
        last = messages[-1]
        if isinstance(last, HumanMessage):
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "bash",
                        "args": {
                            "command": "printf bash-ok > /mnt/user-data/outputs/bash.txt",
                            "evidence_paths": ["/mnt/user-data/outputs/bash.txt"],
                        },
                        "id": "bash-call-1",
                        "type": "tool_call",
                    },
                    {
                        "name": "write_file",
                        "args": {
                            "path": "/mnt/user-data/outputs/ordinary.txt",
                            "content": "普通工具也必须等待审批",
                        },
                        "id": "write-call-1",
                        "type": "tool_call",
                    },
                ],
                usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            )
        if isinstance(last, ToolMessage):
            return AIMessage(
                content="整批工具已经执行。",
                usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            )
        raise TypeError("测试模型只处理用户或工具消息")


class CancelPairingModel(OfflineChatModel):
    """第一轮请求 Bash；第二轮直接回答，用来验证旧 tool call 已补齐。"""

    def _respond(self, messages):
        last = messages[-1]
        if isinstance(last, HumanMessage) and "下一轮" in str(last.content):
            return AIMessage(
                content="下一轮可以正常开始。",
                usage_metadata={"input_tokens": 8, "output_tokens": 4, "total_tokens": 12},
            )
        if isinstance(last, HumanMessage):
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "bash",
                        "args": {"command": "sleep 30", "evidence_paths": []},
                        "id": "cancel-bash-1",
                        "type": "tool_call",
                    }
                ],
                usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            )
        if isinstance(last, ToolMessage):
            return AIMessage(
                content="工具已有明确结果。",
                usage_metadata={"input_tokens": 8, "output_tokens": 4, "total_tokens": 12},
            )
        raise TypeError("测试模型收到无法识别的消息")


class BashOnlyModel(OfflineChatModel):
    """只提出一次带文件证据的 Bash，随后消费账本重放结果。"""

    def _respond(self, messages):
        last = messages[-1]
        if isinstance(last, HumanMessage):
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "bash",
                        "args": {
                            "command": "generate recovered output",
                            "evidence_paths": ["/mnt/user-data/outputs/bash.txt"],
                        },
                        "id": "crash-bash-1",
                        "type": "tool_call",
                    }
                ],
                usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            )
        if isinstance(last, ToolMessage):
            return AIMessage(
                content="已消费恢复后的工具结果。",
                usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            )
        raise TypeError("测试模型收到无法识别的消息")


class SimulatedProcessCrash(BaseException):
    """模拟副作用已经发生，但 Python 来不及写回账本。"""


class FakeDocker:
    """只验证 Agent 编排；真实容器边界由 docker 标记测试单独负责。"""

    def __init__(self, workspace) -> None:
        self.workspace = workspace
        self.calls = 0

    async def execute(self, *, thread_id: str, run_id: str, tool_call_id: str, command: str):
        self.calls += 1
        self.workspace.write_text(thread_id, "/mnt/user-data/outputs/bash.txt", "bash-ok")
        return DockerCommandResult(0, "bash-ok", "", False)

    async def cancel_run(self, run_id: str) -> None:
        return None


class BlockingFakeDocker(FakeDocker):
    """模拟正在运行的外部容器，观察取消是否先调用资源清理。"""

    def __init__(self, workspace) -> None:
        super().__init__(workspace)
        self.started = threading.Event()
        self.cancel_calls = 0

    async def execute(self, *, thread_id: str, run_id: str, tool_call_id: str, command: str):
        self.calls += 1
        self.started.set()
        await asyncio.Event().wait()
        raise AssertionError("阻塞容器只能通过取消结束")

    async def cancel_run(self, run_id: str) -> None:
        self.cancel_calls += 1


def _wait_status(client: TestClient, run_id: str, expected: set[str]) -> dict:
    result = {}
    for _ in range(300):
        result = client.get(f"/api/runs/{run_id}").json()
        if result.get("status") in expected:
            return result
        time.sleep(0.01)
    raise AssertionError(f"Run 未进入预期状态：{result}")


def _submit(client: TestClient, thread_id: str, text: str) -> str:
    response = client.post(
        f"/api/threads/{thread_id}/runs",
        json={"text": text, "attachment_ids": [], "client_request_id": str(uuid4())},
    )
    assert response.status_code == 202
    return response.json()["run_id"]


def test_bash_makes_whole_tool_batch_wait_before_any_side_effect(tmp_path) -> None:
    app = create_app(tmp_path, config=AppConfig(), model=BashBatchModel())
    with TestClient(app) as client:
        fake = FakeDocker(app.state.workspace)
        app.state.docker = fake
        app.state.executor.docker = fake
        thread_id = client.post("/api/threads", json={}).json()["thread_id"]
        run_id = _submit(client, thread_id, "执行一批工具")
        waiting = _wait_status(client, run_id, {"waiting_input"})

        root = app.state.workspace.thread_root(thread_id)
        assert not (root / "outputs" / "bash.txt").exists()
        assert not (root / "outputs" / "ordinary.txt").exists()
        before = client.get(f"/api/runs/{run_id}/tool-executions").json()["items"]
        assert {(item["tool_name"], item["status"], item["attempts"]) for item in before} == {
            ("bash", "prepared", 0),
            ("write_file", "prepared", 0),
        }

        approval = client.get(f"/api/runs/{run_id}/approvals").json()["items"][0]
        resolved = client.post(
            f"/api/approvals/{waiting['pending_approval_id']}/resolve",
            json={"payload_hash": approval["payload_hash"], "decision": "approve", "reason": None},
        )
        assert resolved.status_code == 200
        assert _wait_status(client, run_id, {"succeeded"})["status"] == "succeeded"
        assert fake.calls == 1
        assert (root / "outputs" / "bash.txt").read_text(encoding="utf-8") == "bash-ok"
        assert (root / "outputs" / "ordinary.txt").read_text(encoding="utf-8") == "普通工具也必须等待审批"


def test_restart_marks_running_tools_uncertain_and_requires_checked_resolution(tmp_path) -> None:
    app = create_app(tmp_path, config=AppConfig(), model=OfflineChatModel())
    with TestClient(app) as client:
        thread_id = client.post("/api/threads", json={}).json()["thread_id"]
        run = client.portal.call(
            partial(
                app.state.manager.submit,
                thread_id,
                text="模拟副作用后崩溃",
                client_request_id=str(uuid4()),
            )
        )
        assert client.portal.call(app.state.manager.try_start, run.id)
        path = "/mnt/user-data/outputs/recovered.txt"
        app.state.workspace.write_text(thread_id, path, "已经生成")
        first = client.portal.call(
            partial(
                app.state.ledger.prepare,
                run.id,
                "uncertain-bash-1",
                "bash",
                {"command": "generate report", "evidence_paths": [path]},
                precondition={"evidence_paths": [path]},
            )
        )
        second = client.portal.call(
            partial(
                app.state.ledger.prepare,
                run.id,
                "uncertain-bash-2",
                "bash",
                {"command": "other effect", "evidence_paths": []},
                precondition={"evidence_paths": []},
            )
        )
        client.portal.call(app.state.ledger.begin, first.id)
        client.portal.call(app.state.ledger.begin, second.id)

    restarted = create_app(tmp_path, config=AppConfig(), model=OfflineChatModel())
    with TestClient(restarted) as client:
        run_view = client.get(f"/api/runs/{run.id}").json()
        assert run_view["status"] == "interrupted"
        items = client.get(f"/api/runs/{run.id}/tool-executions").json()["items"]
        assert {(item["id"], item["status"], item["attempts"]) for item in items} == {
            (first.id, "uncertain", 1),
            (second.id, "uncertain", 1),
        }
        blocked = client.post(f"/api/runs/{run.id}/recover")
        assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "RUN_RECOVERY_BLOCKED"

        wrong = client.post(
            f"/api/tool-executions/{first.id}/resolve",
            json={"action": "verify", "evidence": [{"path": path, "sha256": "0" * 64}]},
        )
        assert wrong.status_code == 409 and wrong.json()["error"]["code"] == "TOOL_EVIDENCE_MISMATCH"
        expected = hashlib.sha256("已经生成".encode()).hexdigest()
        verified = client.post(
            f"/api/tool-executions/{first.id}/resolve",
            json={"action": "verify", "evidence": [{"path": path, "sha256": expected}]},
        )
        skipped = client.post(
            f"/api/tool-executions/{second.id}/resolve",
            json={"action": "skip", "evidence": []},
        )
        assert verified.json()["status"] == "succeeded"
        assert skipped.json()["status"] == "failed"
        assert skipped.json()["error_code"] == "TOOL_RESULT_ABANDONED"
        after = client.get(f"/api/runs/{run.id}/tool-executions").json()["items"]
        assert all(item["attempts"] == 1 for item in after)


def test_verified_uncertain_result_recovers_checkpoint_without_reexecuting_tool(tmp_path) -> None:
    first_app = create_app(tmp_path, config=AppConfig(), model=BashOnlyModel())
    with TestClient(first_app) as client:
        first_docker = FakeDocker(first_app.state.workspace)
        first_app.state.docker = first_docker
        first_app.state.executor.docker = first_docker
        thread_id = client.post("/api/threads", json={}).json()["thread_id"]
        run_id = _submit(client, thread_id, "模拟 Bash 写完后进程崩溃")
        waiting = _wait_status(client, run_id, {"waiting_input"})
        approval = client.get(f"/api/runs/{run_id}/approvals").json()["items"][0]

        async def crash_before_ledger_commit(record_id, result):
            raise SimulatedProcessCrash()

        first_app.state.ledger.finish = crash_before_ledger_commit
        approved = client.post(
            f"/api/approvals/{waiting['pending_approval_id']}/resolve",
            json={"payload_hash": approval["payload_hash"], "decision": "approve", "reason": None},
        )
        assert approved.status_code == 200
        for _ in range(300):
            ledger = client.get(f"/api/runs/{run_id}/tool-executions").json()["items"]
            if first_docker.calls == 1 and ledger[0]["status"] == "running":
                break
            time.sleep(0.01)
        assert first_docker.calls == 1 and ledger[0]["attempts"] == 1
        assert first_app.state.workspace.read_text(thread_id, "/mnt/user-data/outputs/bash.txt").content == "bash-ok"

    restarted = create_app(tmp_path, config=AppConfig(), model=BashOnlyModel())
    with TestClient(restarted) as client:
        second_docker = FakeDocker(restarted.state.workspace)
        restarted.state.docker = second_docker
        restarted.state.executor.docker = second_docker
        assert client.get(f"/api/runs/{run_id}").json()["status"] == "interrupted"
        execution = client.get(f"/api/runs/{run_id}/tool-executions").json()["items"][0]
        assert execution["status"] == "uncertain" and execution["attempts"] == 1
        expected = hashlib.sha256(b"bash-ok").hexdigest()
        verified = client.post(
            f"/api/tool-executions/{execution['id']}/resolve",
            json={
                "action": "verify",
                "evidence": [{"path": "/mnt/user-data/outputs/bash.txt", "sha256": expected}],
            },
        )
        assert verified.status_code == 200 and verified.json()["status"] == "succeeded"
        recovery = client.post(f"/api/runs/{run_id}/recover")
        assert recovery.status_code == 202
        assert _wait_status(client, run_id, {"succeeded"})["status"] == "succeeded"
        after = client.get(f"/api/runs/{run_id}/tool-executions").json()["items"][0]
        assert after["attempts"] == 1
        assert second_docker.calls == 0


def test_cancel_waiting_run_pairs_tool_call_and_next_run_can_start(tmp_path) -> None:
    app = create_app(tmp_path, config=AppConfig(), model=CancelPairingModel())
    with TestClient(app) as client:
        thread_id = client.post("/api/threads", json={}).json()["thread_id"]
        first_run = _submit(client, thread_id, "第一轮需要 Bash")
        _wait_status(client, first_run, {"waiting_input"})

        cancelled = client.post(f"/api/runs/{first_run}/cancel")
        assert cancelled.status_code == 200
        assert _wait_status(client, first_run, {"cancelled"})["status"] == "cancelled"
        ledger = client.get(f"/api/runs/{first_run}/tool-executions").json()["items"]
        assert len(ledger) == 1
        assert ledger[0]["status"] == "cancelled" and ledger[0]["error_code"] == "RUN_CANCELLED"
        messages = client.get(f"/api/threads/{thread_id}/messages").json()["items"]
        cancellation = next(item for item in messages if item["role"] == "tool")
        assert cancellation["content"]["tool_call_id"] == "cancel-bash-1"
        assert json.loads(cancellation["content"]["text"])["error"]["code"] == "RUN_CANCELLED"

        second_run = _submit(client, thread_id, "下一轮直接回答")
        assert _wait_status(client, second_run, {"succeeded"})["status"] == "succeeded"


def test_cancel_running_bash_calls_container_cleanup_and_marks_tool_cancelled(tmp_path) -> None:
    app = create_app(tmp_path, config=AppConfig(), model=BashOnlyModel())
    with TestClient(app) as client:
        docker = BlockingFakeDocker(app.state.workspace)
        app.state.docker = docker
        app.state.executor.docker = docker
        thread_id = client.post("/api/threads", json={}).json()["thread_id"]
        run_id = _submit(client, thread_id, "批准后取消运行中的 Bash")
        waiting = _wait_status(client, run_id, {"waiting_input"})
        approval = client.get(f"/api/runs/{run_id}/approvals").json()["items"][0]
        client.post(
            f"/api/approvals/{waiting['pending_approval_id']}/resolve",
            json={"payload_hash": approval["payload_hash"], "decision": "approve", "reason": None},
        ).raise_for_status()
        assert docker.started.wait(timeout=2)

        response = client.post(f"/api/runs/{run_id}/cancel")
        assert response.status_code == 200
        assert _wait_status(client, run_id, {"cancelled"})["status"] == "cancelled"
        assert docker.cancel_calls >= 1
        execution = client.get(f"/api/runs/{run_id}/tool-executions").json()["items"][0]
        assert execution["status"] == "cancelled"
        assert execution["attempts"] == 1 and execution["error_code"] == "RUN_CANCELLED"


def test_docker_create_contract_has_expected_isolation_and_mounts(tmp_path) -> None:
    service = DockerCommandService(tmp_path / "threads", SandboxConfig(), executable="docker-test")
    thread_root = service.threads_root / str(uuid4())
    args = service._create_args(
        thread_root=thread_root,
        run_id=str(uuid4()),
        container_name="agentloom-test",
        command="python --version",
    )
    joined = " ".join(str(item) for item in args)
    assert "--network none" in joined
    assert "--read-only" in args
    assert "--cap-drop ALL" in joined
    assert "no-new-privileges" in args
    assert "--pids-limit 64" in joined and "--memory 512m" in joined
    assert "dst=/mnt/user-data/uploads,readonly" in joined
    assert "dst=/mnt/user-data/tool-results,readonly" in joined
    assert "dst=/mnt/user-data/workspace" in joined and "dst=/mnt/user-data/outputs" in joined
    assert "MODEL_API_KEY" not in joined and ".env" not in joined


@pytest.mark.docker
def test_real_docker_writes_only_mounted_output_and_removes_container(tmp_path) -> None:
    executable = shutil.which("docker")
    if executable is None:
        pytest.skip("本机没有 docker 命令")
    image = "agentloom-python:v1"
    inspected = subprocess.run([executable, "image", "inspect", image], capture_output=True, check=False)
    if inspected.returncode != 0:
        pytest.skip(f"缺少镜像 {image}；先按 README 构建")

    service = DockerCommandService(tmp_path / "threads", SandboxConfig(), executable=executable)
    thread_id = str(uuid4())
    for name in ("workspace", "uploads", "outputs"):
        (service.threads_root / thread_id / name).mkdir(parents=True, exist_ok=True)
    result = asyncio.run(
        service.execute(
            thread_id=thread_id,
            run_id=str(uuid4()),
            tool_call_id="docker-call-1",
            command="printf real-docker > /mnt/user-data/outputs/result.txt",
        )
    )
    assert result.exit_code == 0
    assert (service.threads_root / thread_id / "outputs" / "result.txt").read_text() == "real-docker"
    remaining = subprocess.run(
        [executable, "ps", "--all", "--quiet", "--filter", "label=agentloom.managed=true"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert remaining.stdout.strip() == ""


@pytest.mark.docker
def test_real_docker_timeout_removes_container(tmp_path) -> None:
    executable = shutil.which("docker")
    if executable is None:
        pytest.skip("本机没有 docker 命令")
    image = "agentloom-python:v1"
    inspected = subprocess.run([executable, "image", "inspect", image], capture_output=True, check=False)
    if inspected.returncode != 0:
        pytest.skip(f"缺少镜像 {image}；先按 README 构建")

    service = DockerCommandService(
        tmp_path / "threads",
        SandboxConfig(timeout_seconds=1),
        executable=executable,
    )
    run_id = str(uuid4())
    tool_call_id = "docker-timeout-1"
    with pytest.raises(DockerCommandTimeout, match="容器已停止"):
        asyncio.run(
            service.execute(
                thread_id=str(uuid4()),
                run_id=run_id,
                tool_call_id=tool_call_id,
                command="sleep 30",
            )
        )

    container_name = service._container_name(run_id, tool_call_id)
    remaining = subprocess.run(
        [executable, "container", "inspect", container_name],
        capture_output=True,
        check=False,
    )
    assert remaining.returncode != 0


@pytest.mark.docker
def test_real_docker_limits_mounts_secrets_and_cancel(tmp_path, monkeypatch) -> None:
    executable = shutil.which("docker")
    if executable is None:
        pytest.skip("本机没有 docker 命令")
    image = "agentloom-python:v1"
    inspected = subprocess.run([executable, "image", "inspect", image], capture_output=True, check=False)
    if inspected.returncode != 0:
        pytest.skip(f"缺少镜像 {image}；先按 README 构建")

    # 宿主机即使存在模型密钥，也不能因为继承环境变量而进入容器。
    monkeypatch.setenv("MODEL_API_KEY", "host-secret-must-not-enter-container")
    service = DockerCommandService(tmp_path / "threads", SandboxConfig(), executable=executable)
    thread_id = str(uuid4())
    run_id = str(uuid4())
    tool_call_id = "docker-cancel-1"
    thread_root = service.threads_root / thread_id

    async def scenario() -> None:
        task = asyncio.create_task(
            service.execute(
                thread_id=thread_id,
                run_id=run_id,
                tool_call_id=tool_call_id,
                command="sleep 30",
            )
        )
        container_name = service._container_name(run_id, tool_call_id)
        metadata = None
        for _ in range(100):
            await asyncio.sleep(0.05)
            result = subprocess.run(
                [executable, "container", "inspect", container_name],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0:
                metadata = json.loads(result.stdout)[0]
                break
        assert metadata is not None, "真实容器没有在预期时间内启动"

        host_config = metadata["HostConfig"]
        assert host_config["ReadonlyRootfs"] is True
        assert host_config["NetworkMode"] == "none"
        assert host_config["Memory"] == 512 * 1024 * 1024
        assert host_config["NanoCpus"] == 1_000_000_000
        assert host_config["PidsLimit"] == 64
        assert "ALL" in host_config["CapDrop"]
        assert "no-new-privileges" in host_config["SecurityOpt"]

        mounts = metadata["Mounts"]
        assert {item["Destination"] for item in mounts} == {
            "/mnt/user-data/workspace",
            "/mnt/user-data/uploads",
            "/mnt/user-data/outputs",
            "/mnt/user-data/tool-results",
        }
        assert not any(item["Destination"] == "/var/run/docker.sock" for item in mounts)
        for item in mounts:
            Path(item["Source"]).resolve().relative_to(thread_root.resolve())
        environment_names = {item.partition("=")[0] for item in metadata["Config"]["Env"]}
        assert "MODEL_API_KEY" not in environment_names

        # 与 RunExecutor.cancel 相同：先移除外部容器，再取消等待它的协程。
        await service.cancel_run(run_id)
        if not task.done():
            task.cancel()
        outcome = (await asyncio.gather(task, return_exceptions=True))[0]
        assert isinstance(outcome, asyncio.CancelledError) or (
            isinstance(outcome, DockerCommandResult) and outcome.exit_code != 0
        )
        remaining = subprocess.run(
            [executable, "container", "inspect", container_name],
            capture_output=True,
            check=False,
        )
        assert remaining.returncode != 0

    asyncio.run(scenario())
