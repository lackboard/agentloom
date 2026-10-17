"""离线展示 M1 的入场、后台执行、SSE 回放、计量与取消。"""

import asyncio
import json
import sys
import threading
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from fastapi.testclient import TestClient
from pydantic import PrivateAttr

from agentloom.api import create_app
from agentloom.config import AppConfig
from agentloom.models.fake import OfflineChatModel


class DemoModel(OfflineChatModel):
    """遇到“等待取消”时保持请求，供取消演示使用。"""

    _cancel_started: threading.Event = PrivateAttr(default_factory=threading.Event)

    @property
    def cancel_started(self) -> threading.Event:
        return self._cancel_started

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        if "等待取消" in str(messages[-1].content):
            self._cancel_started.set()
            await asyncio.sleep(30)
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def wait_status(client: TestClient, run_id: str, expected: set[str]) -> dict:
    for _ in range(200):
        result = client.get(f"/api/runs/{run_id}").json()
        if result["status"] in expected:
            return result
        time.sleep(0.01)
    raise RuntimeError(f"Run 未进入预期状态：{result}")


def sse_events(response) -> list[dict]:
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    with TemporaryDirectory(prefix=".m1-demo-", dir=Path.cwd()) as folder:
        storage = Path(folder)
        model = DemoModel()
        with TestClient(create_app(storage, config=AppConfig(), model=model)) as client:
            thread_id = client.post("/api/threads", json={}).json()["thread_id"]
            url = f"/api/threads/{thread_id}/runs"
            request_id = str(uuid4())
            body = {"text": "请计算 2 + 3", "attachment_ids": [], "client_request_id": request_id}
            first = client.post(url, json=body)
            repeat = client.post(url, json=body)
            changed = client.post(url, json={**body, "text": "different"})
            run_id = first.json()["run_id"]
            success = wait_status(client, run_id, {"succeeded"})
            replay = sse_events(client.get(first.json()["events_url"], params={"after_seq": 2}))

            print(f"submit: {first.status_code} run_id={run_id} accepted_status={first.json()['status']}")
            print(f"repeat: {repeat.status_code} same_run={repeat.json()['run_id'] == run_id}")
            print(f"changed_id_body: {changed.status_code} code={changed.json()['error']['code']}")
            print(f"worker: final_status={success['status']} usage={success['usage']}")
            print(f"sse_reconnect_after_2: {[(event['seq'], event['type']) for event in replay]}")

            cancel_body = {
                "text": "等待取消",
                "attachment_ids": [],
                "client_request_id": str(uuid4()),
            }
            cancel_run_id = client.post(url, json=cancel_body).json()["run_id"]
            if not model.cancel_started.wait(timeout=2):
                raise RuntimeError("取消演示没有进入模型调用")
            cancel_response = client.post(f"/api/runs/{cancel_run_id}/cancel").json()
            cancelled = wait_status(client, cancel_run_id, {"cancelled"})
            cancel_events = sse_events(client.get(f"/api/runs/{cancel_run_id}/events"))
            print(f"cancel: accepted={cancel_response['status']} final={cancelled['status']}")
            print(
                "cancel_terminal_events: "
                f"{[event['data'] for event in cancel_events if event['type'] == 'run.finished']}"
            )
            message_count = len(client.get(f"/api/threads/{thread_id}/messages").json()["items"])
            print(f"messages_after_success_and_cancel: {message_count}")

        print("storage: app.sqlite and checkpoints.sqlite are separate files")


if __name__ == "__main__":
    main()
