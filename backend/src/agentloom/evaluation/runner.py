"""通过正式 HTTP/后台执行链运行固定任务，并保存失败在内的完整观察。"""

import json
import time
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from agentloom.api import create_app
from agentloom.config import AppConfig
from agentloom.evaluation.grading import grade_observation
from agentloom.evaluation.schema import ArtifactObservation, EvaluationTask, Observation, TaskResult

TERMINAL = {"succeeded", "failed", "cancelled"}


class EvaluationRunner:
    def __init__(self, *, config: AppConfig, data_dir: Path, timeout_seconds: float = 240.0) -> None:
        self.config = config
        self.data_dir = data_dir
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def _resolve_pending_approval(client: TestClient, run_id: str) -> bool:
        response = client.get(f"/api/runs/{run_id}/approvals")
        response.raise_for_status()
        pending = next(
            (item for item in response.json()["items"] if item["status"] == "pending" and item["checkpoint_ready"]),
            None,
        )
        if pending is None:
            return False
        resolved = client.post(
            f"/api/approvals/{pending['approval_id']}/resolve",
            json={"payload_hash": pending["payload_hash"], "decision": "approve"},
        )
        resolved.raise_for_status()
        return True

    @staticmethod
    def _read_artifacts(client: TestClient, thread_id: str) -> list[ArtifactObservation]:
        response = client.get(f"/api/threads/{thread_id}/artifacts")
        response.raise_for_status()
        artifacts = []
        for item in response.json()["items"]:
            content = None
            if item["kind"] != "upload" and (item["mime_type"].startswith("text/") or "json" in item["mime_type"]):
                downloaded = client.get(item["content_url"])
                if downloaded.status_code == 200:
                    content = downloaded.content.decode("utf-8", errors="replace")
            artifacts.append(ArtifactObservation(name=item["display_name"], kind=item["kind"], content=content))
        return artifacts

    def _run_one(self, client: TestClient, task: EvaluationTask, repetition: int) -> TaskResult:
        started = time.monotonic()
        approval_wait = 0.0
        thread = client.post("/api/threads", json={"title": f"eval:{task.id}:{repetition}"})
        thread.raise_for_status()
        thread_id = thread.json()["thread_id"]
        attachment_ids = []
        for fixture in task.attachments:
            uploaded = client.post(
                f"/api/threads/{thread_id}/uploads",
                files={"file": (fixture.name, fixture.content.encode("utf-8"), fixture.mime_type)},
            )
            uploaded.raise_for_status()
            attachment_ids.append(uploaded.json()["artifact_id"])
        submitted = client.post(
            f"/api/threads/{thread_id}/runs",
            json={
                "text": task.prompt,
                "attachment_ids": attachment_ids,
                "client_request_id": str(uuid4()),
            },
        )
        submitted.raise_for_status()
        run_id = submitted.json()["run_id"]
        deadline = time.monotonic() + self.timeout_seconds
        run = None
        while time.monotonic() < deadline:
            response = client.get(f"/api/runs/{run_id}")
            response.raise_for_status()
            run = response.json()
            if run["status"] in TERMINAL:
                break
            if run["status"] == "waiting_input":
                approval_started = time.monotonic()
                if self._resolve_pending_approval(client, run_id):
                    approval_wait += time.monotonic() - approval_started
            time.sleep(0.05)
        else:
            client.post(f"/api/runs/{run_id}/cancel")
            raise TimeoutError(f"任务 {task.id} 超过 {self.timeout_seconds:g}s")
        assert run is not None

        message_response = client.get(f"/api/threads/{thread_id}/messages")
        message_response.raise_for_status()
        messages = message_response.json()["items"]
        final_text = next(
            (
                str(item["content"].get("text", ""))
                for item in reversed(messages)
                if item["role"] == "assistant" and str(item["content"].get("text", "")).strip()
            ),
            "",
        )
        proposed = sum(len(item["content"].get("tool_calls") or []) for item in messages if item["role"] == "assistant")
        tool_response = client.get(f"/api/runs/{run_id}/tool-executions")
        tool_response.raise_for_status()
        tools = tool_response.json()["items"]
        subagent_response = client.get(f"/api/runs/{run_id}/subagents")
        subagent_response.raise_for_status()
        observation = Observation(
            run_id=run_id,
            status=run["status"],
            final_text=final_text,
            tool_names=[item["tool_name"] for item in tools],
            proposed_tool_calls=proposed,
            admitted_tool_calls=len(tools),
            artifact_items=self._read_artifacts(client, thread_id),
            subagent_count=len(subagent_response.json()["items"]),
            wall_seconds=time.monotonic() - started,
            approval_wait_seconds=approval_wait,
            model_attempts=run["usage"]["model_attempts"],
            tool_executions=run["usage"]["tool_executions"],
            input_tokens=run["usage"]["input_tokens"],
            output_tokens=run["usage"]["output_tokens"],
            usage_complete=run["usage"]["complete"],
            error=run["error"],
        )
        return grade_observation(task, observation, repetition=repetition)

    def run(self, tasks: list[EvaluationTask], *, repeat: int = 1) -> list[TaskResult]:
        results: list[TaskResult] = []
        self.data_dir.mkdir(parents=True, exist_ok=True)
        with TestClient(create_app(self.data_dir, config=self.config)) as client:
            for repetition in range(1, repeat + 1):
                for task in tasks:
                    print(f"[{len(results) + 1}/{len(tasks) * repeat}] {task.id} repetition={repetition}", flush=True)
                    try:
                        result = self._run_one(client, task, repetition)
                    except Exception as exc:
                        result = TaskResult(
                            task_id=task.id,
                            category=task.category,
                            repetition=repetition,
                            variant=task.variant,
                            pair_id=task.pair_id,
                            outcome="error",
                            checks=[],
                            runner_error=f"{type(exc).__name__}: {exc}",
                        )
                    results.append(result)
                    print(f"  -> {result.outcome}", flush=True)
        return results


def write_json_report(path: Path, *, metadata: dict, results: list[TaskResult], summary: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "metadata": metadata,
        "summary": summary,
        "results": [result.model_dump(mode="json") for result in results],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
