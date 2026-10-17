"""FastAPI 生命周期、Run API 与可重连 SSE。"""

import asyncio
import json
from collections.abc import Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from urllib.parse import quote
from uuid import uuid4

from fastapi import FastAPI, File, Header, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from agentloom.agents.factory import create_loom_agent
from agentloom.api.schemas import (
    CreateMemory,
    CreateThread,
    DeleteMemory,
    ResolveApproval,
    ResolveToolExecution,
    SubmitRun,
    UpdateMemory,
)
from agentloom.artifacts import ArtifactIntegrityError, ArtifactNotFound, ArtifactService
from agentloom.artifacts.service import MAX_ARTIFACT_BYTES
from agentloom.config import AppConfig, load_config
from agentloom.mcp import McpManager
from agentloom.memory import MemoryConflict, MemoryNotFound, MemoryService
from agentloom.models.factory import create_chat_model
from agentloom.persistence.database import create_sessionmaker, migrate_database
from agentloom.runtime.approvals import (
    ApprovalConflict,
    ApprovalNotFound,
    ApprovalNotReady,
    ApprovalService,
)
from agentloom.runtime.events import EventBroker
from agentloom.runtime.executor import TERMINAL_STATUSES, RunExecutor, RunRecoveryBlocked
from agentloom.runtime.ledger import (
    ToolEvidenceMismatch,
    ToolExecutionNotFound,
    ToolLedgerService,
    ToolResolutionConflict,
)
from agentloom.runtime.manager import (
    AttachmentNotFound,
    RequestConflict,
    RunManager,
    RunNotFound,
    ThreadBusy,
    ThreadNotFound,
)
from agentloom.sandbox import DockerCommandService, WorkspaceError, WorkspaceService
from agentloom.skills import SkillLoader
from agentloom.subagents import SubagentExecutor, SubagentTaskRepository
from agentloom.tools import get_builtin_tools


def _error(code: str, message: str, status: int) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "request_id": str(uuid4())}},
    )


def _approval_payload(record) -> dict:
    """对外返回审批业务字段，不暴露宿主机路径或任意 resume 入口。"""
    return {
        "approval_id": record.id,
        "run_id": record.run_id,
        "kind": record.kind,
        "payload_hash": record.payload_hash,
        "payload": record.payload,
        "status": record.status,
        "response": record.response,
        "checkpoint_ready": record.checkpoint_id is not None,
        "created_at": record.created_at,
        "resolved_at": record.resolved_at,
        "consumed_at": record.consumed_at,
    }


def _run_summary(run) -> dict | None:
    """供线程列表和恢复接口复用的最小 Run 摘要。"""
    if run is None:
        return None
    return {
        "run_id": run.id,
        "status": run.status,
        "stop_reason": run.stop_reason,
        "created_at": run.created_at,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
    }


def _artifact_payload(record) -> dict:
    """产物元数据只暴露虚拟路径和下载入口，不泄漏宿主机路径。"""
    return {
        "artifact_id": record.id,
        "thread_id": record.thread_id,
        "run_id": record.run_id,
        "kind": record.kind,
        "display_name": record.display_name,
        "virtual_path": f"/mnt/user-data/{record.relative_path}",
        "sha256": record.sha256,
        "size_bytes": record.size_bytes,
        "mime_type": record.mime_type,
        "created_at": record.created_at,
        "content_url": f"/api/artifacts/{record.id}/content",
    }


def create_app(
    data_dir: Path | None = None,
    config: AppConfig | None = None,
    *,
    model: BaseChatModel | None = None,
    tools: Sequence[BaseTool] | None = None,
) -> FastAPI:
    settings = config or load_config()
    app_path = data_dir / "app.sqlite" if data_dir else settings.resolve_path(settings.database.app_path)
    checkpoint_path = (
        data_dir / "checkpoints.sqlite" if data_dir else settings.resolve_path(settings.database.checkpoint_path)
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await asyncio.to_thread(migrate_database, app_path)
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        sessions = create_sessionmaker(app_path)
        broker = EventBroker()
        workspace = WorkspaceService(app_path.parent / "threads")
        artifacts = ArtifactService(sessions, workspace)
        ledger = ToolLedgerService(sessions)
        subagent_repository = SubagentTaskRepository(sessions, event_notifier=broker.notify)
        docker = DockerCommandService(workspace.root, settings.sandbox)
        skills = SkillLoader(
            settings.resolve_path(settings.skills.directory),
            max_active=settings.skills.max_active_per_agent,
        )
        memories = MemoryService(sessions)
        mcp = McpManager(settings.mcp, settings.resolve_path(settings.mcp.reference_library_script))
        app.state.config = settings
        app.state.manager = RunManager(
            sessions,
            model_name=settings.models.default.model,
            config_snapshot=settings.models.default.model_dump(mode="json"),
            budget=settings.runtime.model_dump(mode="json"),
            event_notifier=broker.notify,
        )
        approvals = ApprovalService(sessions, workspace, ledger, event_notifier=broker.notify)
        app.state.event_broker = broker
        app.state.workspace = workspace
        app.state.artifacts = artifacts
        app.state.ledger = ledger
        app.state.approvals = approvals
        app.state.docker = docker
        app.state.skills = skills
        app.state.memories = memories
        app.state.mcp = mcp
        async with AsyncSqliteSaver.from_conn_string(str(checkpoint_path)) as saver:
            await saver.setup()
            app.state.checkpointer = saver
            # checkpoint 可用后再建立外部工具注册表；MCP 失败只移除该来源的工具。
            mcp_tools = await mcp.start()
            chat_model = model or create_chat_model(settings.models.default)
            selected_tools = [*(get_builtin_tools() if tools is None else list(tools)), *mcp_tools]
            app.state.tools = selected_tools
            # 工具集合冻结后再对账上次进程遗留的 Run 和外部资源。
            orphaned_run_ids = await ledger.mark_orphaned_running_uncertain()
            orphaned_run_ids.update(await subagent_repository.interrupt_orphaned())
            await app.state.manager.interrupt_orphaned_runs(orphaned_run_ids)
            await docker.cleanup_orphans()
            subagents = SubagentExecutor(
                model=chat_model,
                tools=selected_tools,
                workspace=workspace,
                artifacts=artifacts,
                repository=subagent_repository,
                timeout_seconds=settings.runtime.subagent_timeout_seconds,
                max_tasks_per_run=settings.runtime.max_subagents_per_run,
                max_running=settings.runtime.max_running_subagents,
            )
            app.state.subagents = subagents
            agent = create_loom_agent(
                model=chat_model,
                tools=selected_tools,
                checkpointer=saver,
                max_model_attempts=settings.runtime.max_model_attempts_per_run,
                max_tool_executions=settings.runtime.max_tool_executions_per_run,
                context_window=settings.models.default.context_window,
                max_output_tokens=settings.models.default.max_output_tokens,
                compaction_fraction=settings.context.compaction_fraction,
                tool_preview_bytes=settings.context.tool_preview_bytes,
            )
            app.state.agent = agent
            executor = RunExecutor(
                app.state.manager,
                agent,
                workspace,
                artifacts,
                ledger,
                approvals,
                docker,
                skills,
                memories,
                subagents,
                max_running=settings.runtime.max_running_runs,
                max_model_attempts=settings.runtime.max_model_attempts_per_run,
                max_tool_executions=settings.runtime.max_tool_executions_per_run,
            )
            app.state.executor = executor
            try:
                yield
            finally:
                await executor.close()
                await mcp.close()
                await sessions.kw["bind"].dispose()

    app = FastAPI(title="AgentLoom API", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.server.allowed_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.post("/api/threads", status_code=201)
    async def create_thread(body: CreateThread, request: Request):
        thread = await request.app.state.manager.create_thread(title=body.title, profile=body.profile)
        await asyncio.to_thread(request.app.state.workspace.ensure_thread, thread.id)
        return {"thread_id": thread.id, "title": thread.title, "agent_profile": thread.agent_profile}

    @app.get("/api/threads")
    async def get_threads(request: Request, limit: int = Query(default=100, ge=1, le=200)):
        """列出最近活跃线程；刷新页面时不需要重新提交 Run。"""
        rows = await request.app.state.manager.list_threads(limit=limit)
        return {
            "items": [
                {
                    "thread_id": thread.id,
                    "title": thread.title,
                    "agent_profile": thread.agent_profile,
                    "created_at": thread.created_at,
                    "updated_at": thread.updated_at,
                    "latest_run": _run_summary(latest_run),
                }
                for thread, latest_run in rows
            ],
            "next_cursor": None,
        }

    @app.get("/api/threads/{thread_id}")
    async def get_thread(thread_id: str, request: Request):
        """返回工作台恢复所需的线程、最新 Run 和 checkpoint 投影。"""
        try:
            thread, latest_run = await request.app.state.manager.get_thread(thread_id)
        except ThreadNotFound:
            return _error("THREAD_NOT_FOUND", "Thread does not exist", 404)
        snapshot = await request.app.state.agent.aget_state({"configurable": {"thread_id": thread_id}})
        values = snapshot.values or {}
        return {
            "thread_id": thread.id,
            "title": thread.title,
            "agent_profile": thread.agent_profile,
            "created_at": thread.created_at,
            "updated_at": thread.updated_at,
            "latest_run": _run_summary(latest_run),
            "todos": values.get("todos", []),
        }

    @app.get("/api/skills")
    async def get_skills(request: Request):
        """返回启动时发现的轻量元数据，避免把所有 Skill 正文发给客户端。"""
        return {"skills": [item.model_dump(mode="json") for item in request.app.state.skills.list_skills()]}

    @app.get("/api/tools")
    async def get_tools(request: Request):
        """展示工具来源和 MCP 诊断，不返回命令、环境变量或宿主机路径。"""
        diagnostic = request.app.state.mcp.diagnostic
        return {
            "items": [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "source": (tool.metadata or {}).get("source", "builtin"),
                    "server": (tool.metadata or {}).get("server"),
                    "enabled": True,
                }
                for tool in request.app.state.tools
            ],
            "mcp_servers": [
                {
                    "name": diagnostic.server,
                    "status": diagnostic.status,
                    "error": None
                    if diagnostic.code is None
                    else {"code": diagnostic.code, "message": diagnostic.message},
                }
            ],
        }

    def memory_payload(record) -> dict:
        return {
            "id": record.id,
            "scope_key": record.scope_key,
            "category": record.category,
            "memory_key": record.memory_key,
            "content": record.content,
            "status": record.status,
            "source_run_id": record.source_run_id,
            "version": record.version,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
            "expires_at": record.expires_at,
        }

    @app.get("/api/memories")
    async def get_memories(request: Request):
        records = await request.app.state.memories.list_active()
        return {"items": [memory_payload(record) for record in records], "next_cursor": None}

    @app.post("/api/memories", status_code=201)
    async def create_memory(body: CreateMemory, request: Request):
        try:
            record = await request.app.state.memories.create_active(
                category=body.category,
                memory_key=body.memory_key,
                content=body.content,
            )
        except MemoryConflict as exc:
            return _error(exc.code, str(exc), 409)
        return memory_payload(record)

    @app.patch("/api/memories/{memory_id}")
    async def update_memory(memory_id: str, body: UpdateMemory, request: Request):
        try:
            record = await request.app.state.memories.update(
                memory_id,
                content=body.content,
                expected_version=body.expected_version,
            )
        except MemoryNotFound as exc:
            return _error(exc.code, str(exc), 404)
        except MemoryConflict as exc:
            return _error(exc.code, str(exc), 409)
        return memory_payload(record)

    @app.delete("/api/memories/{memory_id}")
    async def delete_memory(memory_id: str, body: DeleteMemory, request: Request):
        try:
            record = await request.app.state.memories.delete(memory_id, expected_version=body.expected_version)
        except MemoryNotFound as exc:
            return _error(exc.code, str(exc), 404)
        except MemoryConflict as exc:
            return _error(exc.code, str(exc), 409)
        return memory_payload(record)

    @app.post("/api/threads/{thread_id}/uploads", status_code=201)
    async def upload_file(thread_id: str, request: Request, file: UploadFile = File(...)):
        content = await file.read(MAX_ARTIFACT_BYTES + 1)
        try:
            record = await request.app.state.artifacts.register_upload(
                thread_id,
                file.filename or "upload.bin",
                content,
            )
        except ArtifactNotFound:
            return _error("THREAD_NOT_FOUND", "Thread does not exist", 404)
        except (ArtifactIntegrityError, WorkspaceError, ValueError) as exc:
            return _error(getattr(exc, "code", "INVALID_UPLOAD"), str(exc), 422)
        return _artifact_payload(record)

    @app.post("/api/threads/{thread_id}/runs", status_code=202)
    async def submit_run(thread_id: str, body: SubmitRun, request: Request):
        try:
            run = await request.app.state.manager.submit(
                thread_id,
                text=body.text,
                client_request_id=str(body.client_request_id),
                attachment_ids=body.attachment_ids,
            )
        except ThreadNotFound:
            return _error("THREAD_NOT_FOUND", "Thread does not exist", 404)
        except RequestConflict:
            return _error("REQUEST_CONFLICT", "Request ID already has different content", 409)
        except AttachmentNotFound:
            return _error("ATTACHMENT_NOT_FOUND", "Attachment does not exist in this thread", 422)
        except ThreadBusy:
            return _error("THREAD_BUSY", "Thread has an unfinished Run", 409)
        request.app.state.executor.start(run.id)
        return {
            "run_id": run.id,
            "thread_id": run.thread_id,
            "status": run.status,
            "events_url": f"/api/runs/{run.id}/events",
        }

    @app.get("/api/runs/{run_id}")
    async def get_run(run_id: str, request: Request):
        run = await request.app.state.manager.get_run(run_id)
        if run is None:
            return _error("RUN_NOT_FOUND", "Run does not exist", 404)
        pending_approval = await request.app.state.approvals.pending_for_run(run_id)
        return {
            "run_id": run.id,
            "thread_id": run.thread_id,
            "status": run.status,
            "stop_reason": run.stop_reason,
            "error": None if run.error_code is None else {"code": run.error_code, "message": run.error_message},
            "usage": {
                "model_attempts": run.model_attempts,
                "tool_executions": run.tool_executions_count,
                "input_tokens": run.input_tokens,
                "output_tokens": run.output_tokens,
                "complete": bool(run.usage_complete),
            },
            "pending_approval_id": None if pending_approval is None else pending_approval.id,
        }

    @app.get("/api/runs/{run_id}/tool-executions")
    async def get_tool_executions(run_id: str, request: Request):
        if await request.app.state.manager.get_run(run_id) is None:
            return _error("RUN_NOT_FOUND", "Run does not exist", 404)
        records = await request.app.state.ledger.list_for_run(run_id)
        return {
            "items": [
                {
                    "id": record.id,
                    "scope": record.scope,
                    "tool_call_id": record.tool_call_id,
                    "tool_name": record.tool_name,
                    "args_hash": record.args_hash,
                    "args": record.args,
                    "replay_class": record.replay_class,
                    "status": record.status,
                    "precondition": record.precondition,
                    "error_code": record.error_code,
                    "attempts": record.attempts,
                    "result": record.result,
                }
                for record in records
            ]
        }

    @app.get("/api/runs/{run_id}/approvals")
    async def get_approvals(run_id: str, request: Request):
        if await request.app.state.manager.get_run(run_id) is None:
            return _error("RUN_NOT_FOUND", "Run does not exist", 404)
        records = await request.app.state.approvals.list_for_run(run_id)
        return {"items": [_approval_payload(record) for record in records]}

    @app.get("/api/runs/{run_id}/subagents")
    async def get_subagents(run_id: str, request: Request):
        if await request.app.state.manager.get_run(run_id) is None:
            return _error("RUN_NOT_FOUND", "Run does not exist", 404)
        records = await request.app.state.subagents.repository.list_for_run(run_id)
        return {
            "items": [
                {
                    "task_id": record.id,
                    "run_id": record.run_id,
                    "parent_tool_call_id": record.parent_tool_call_id,
                    "agent_type": record.agent_type,
                    "status": record.status,
                    "prompt": record.prompt,
                    "result": record.result,
                    "deadline_at": record.deadline_at,
                }
                for record in records
            ]
        }

    @app.post("/api/approvals/{approval_id}/resolve")
    async def resolve_approval(approval_id: str, body: ResolveApproval, request: Request):
        try:
            record, _new = await request.app.state.approvals.resolve(
                approval_id,
                payload_hash=body.payload_hash,
                decision=body.decision,
                reason=body.reason,
            )
        except ApprovalNotFound:
            return _error("APPROVAL_NOT_FOUND", "Approval does not exist", 404)
        except (ApprovalConflict, ApprovalNotReady) as exc:
            return _error(exc.code, str(exc), 409)
        request.app.state.executor.resume(record)
        return _approval_payload(record)

    @app.post("/api/tool-executions/{execution_id}/resolve")
    async def resolve_tool_execution(execution_id: str, body: ResolveToolExecution, request: Request):
        try:
            record = await request.app.state.ledger.resolve_uncertain(
                execution_id,
                action=body.action,
                evidence=[item.model_dump() for item in body.evidence],
                workspace=request.app.state.workspace,
            )
        except ToolExecutionNotFound:
            return _error("TOOL_EXECUTION_NOT_FOUND", "Tool execution does not exist", 404)
        except (ToolResolutionConflict, ToolEvidenceMismatch) as exc:
            return _error(exc.code, str(exc), 409)
        return {
            "id": record.id,
            "run_id": record.run_id,
            "status": record.status,
            "error_code": record.error_code,
            "result": record.result,
        }

    @app.post("/api/runs/{run_id}/recover", status_code=202)
    async def recover_run(run_id: str, request: Request):
        try:
            status = await request.app.state.executor.recover(run_id)
        except RunNotFound:
            return _error("RUN_NOT_FOUND", "Run does not exist", 404)
        except RunRecoveryBlocked as exc:
            return _error(exc.code, str(exc), 409)
        return {"run_id": run_id, "status": status}

    @app.get("/api/threads/{thread_id}/messages")
    async def get_messages(thread_id: str, request: Request):
        try:
            rows = await request.app.state.manager.get_messages(thread_id)
        except ThreadNotFound:
            return _error("THREAD_NOT_FOUND", "Thread does not exist", 404)
        return {
            "items": [
                {
                    "id": row.id,
                    "seq": row.seq,
                    "role": row.role,
                    "content": json.loads(row.content_json),
                    "status": row.status,
                }
                for row in rows
            ],
            "next_cursor": None,
        }

    @app.get("/api/threads/{thread_id}/artifacts")
    async def get_thread_artifacts(thread_id: str, request: Request):
        try:
            records = await request.app.state.artifacts.list_for_thread(thread_id)
        except ArtifactNotFound:
            return _error("THREAD_NOT_FOUND", "Thread does not exist", 404)
        return {"items": [_artifact_payload(record) for record in records]}

    @app.get("/api/artifacts/{artifact_id}")
    async def get_artifact(artifact_id: str, request: Request):
        try:
            record = await request.app.state.artifacts.get(artifact_id)
        except ArtifactNotFound:
            return _error("ARTIFACT_NOT_FOUND", "Artifact does not exist", 404)
        return _artifact_payload(record)

    @app.get("/api/artifacts/{artifact_id}/content")
    async def get_artifact_content(artifact_id: str, request: Request):
        try:
            record, content = await request.app.state.artifacts.read_content(artifact_id)
        except ArtifactNotFound:
            return _error("ARTIFACT_NOT_FOUND", "Artifact does not exist", 404)
        except ArtifactIntegrityError as exc:
            return _error(exc.code, str(exc), 409)
        filename = quote(record.display_name, safe="")
        return Response(
            content=content,
            media_type=record.mime_type,
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{filename}",
                "ETag": f'"{record.sha256}"',
            },
        )

    #  FastAPI 里实现 SSE（Server-Sent Events）流式推送的端点，用来把一个 Run 产生的所有事件按顺序、实时地推送给客户端。
    @app.get("/api/runs/{run_id}/events")
    async def stream_events(
        run_id: str,
        request: Request,
        after_seq: int = Query(default=0, ge=0),
        # last_event_id：从 HTTP 请求头 Last-Event-ID 读取。这是 SSE
        # 协议的标准断线重连机制：浏览器在连接断开后重连时，会自动带上最后收到的事件 ID，服务器据此续传，不重复推送。
        last_event_id: Annotated[int | None, Header(alias="Last-Event-ID", ge=0)] = None,
    ):
        if await request.app.state.manager.get_run(run_id) is None:
            return _error("RUN_NOT_FOUND", "Run does not exist", 404)
        # cursor 是起点序号：取 after_seq 和 last_event_id 里更大的那个。
        cursor = max(after_seq, last_event_id or 0)

        async def generate():
            # nonlocal cursor：因为下面要修改外层函数的 cursor 变量。
            nonlocal cursor
            manager = request.app.state.manager
            broker = request.app.state.event_broker
            while True:
                # 先记版本再查库；事件若正好在二者之间提交，等待条件会立即满足。
                version = broker.version(run_id)
                rows = await manager.get_events_after(run_id, cursor)
                if rows:
                    for row in rows:
                        cursor = row.seq
                        envelope = {
                            "version": 1,
                            "run_id": row.run_id,
                            "seq": row.seq,
                            "type": row.event_type,
                            "scope": row.scope,
                            "timestamp": row.created_at,
                            "data": json.loads(row.payload_json),
                        }
                        # yield 的字符串是 SSE 协议格式
                        yield (
                            f"id: {row.seq}\n"
                            f"event: {row.event_type}\n"
                            f"data: {json.dumps(envelope, ensure_ascii=False, separators=(',', ':'))}\n\n"
                        )
                    continue
                run = await manager.get_run(run_id)
                if run is None or run.status in TERMINAL_STATUSES:
                    break
                if await request.is_disconnected():
                    break
                changed = await broker.wait_for_change(run_id, version)
                if not changed:
                    yield ": keep-alive\n\n"

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            # X-Accel-Buffering: no：告诉 Nginx 不要缓冲，
            # 立即转发。不加这个，Nginx 可能会把流攒够一定大小才发，导致实时性失效。
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/runs/{run_id}/cancel")
    async def cancel_run(run_id: str, request: Request):
        try:
            status = await request.app.state.executor.cancel(run_id)
        except RunNotFound:
            return _error("RUN_NOT_FOUND", "Run does not exist", 404)
        return {"run_id": run_id, "status": status}

    return app
