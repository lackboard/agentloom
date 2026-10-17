"""通过 LoomContext 访问线程文件和登记产物的内置工具。"""

import asyncio
import json

from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from agentloom.artifacts.service import ArtifactError
from agentloom.runtime.approvals import ApprovalError
from agentloom.runtime.context import LoomContext
from agentloom.sandbox import WorkspaceError


def _error(error: WorkspaceError | ArtifactError | ApprovalError) -> dict:
    return {"ok": False, "error": {"code": error.code, "message": str(error)}}


@tool
async def list_dir(path: str, runtime: ToolRuntime[LoomContext]) -> dict:
    """列出当前线程虚拟工作目录；路径必须在 /mnt/user-data 下。"""
    try:
        items = await asyncio.to_thread(runtime.context.workspace.list_dir, runtime.context.thread_id, path)
        return {"ok": True, "path": path, "items": items}
    except WorkspaceError as exc:
        return _error(exc)


@tool
async def read_file(
    path: str,
    runtime: ToolRuntime[LoomContext],
    start_char: int = 0,
    max_chars: int = 512,
) -> dict:
    """分块读取 UTF-8 文件；大结果引用可用 start_char 连续翻页。"""
    try:
        if start_char < 0 or not 1 <= max_chars <= 512:
            raise WorkspaceError("start_char 必须非负，max_chars 必须在 1～512 之间")
        result = await asyncio.to_thread(runtime.context.workspace.read_text, runtime.context.thread_id, path)
        content = result.content[start_char : start_char + max_chars]
        next_start = start_char + len(content)
        return {
            "ok": True,
            "path": result.virtual_path,
            "content": content,
            "sha256": result.sha256,
            "size_bytes": result.size_bytes,
            "start_char": start_char,
            "next_start_char": next_start if next_start < len(result.content) else None,
            "truncated": next_start < len(result.content),
        }
    except WorkspaceError as exc:
        return _error(exc)


@tool
async def write_file(path: str, content: str, runtime: ToolRuntime[LoomContext]) -> dict:
    """新建 UTF-8 文本文件；仅允许 workspace/outputs，已有文件不会被覆盖。"""
    try:
        result = await asyncio.to_thread(
            runtime.context.workspace.write_text,
            runtime.context.thread_id,
            path,
            content,
        )
        return {
            "ok": True,
            "path": result.virtual_path,
            "sha256": result.sha256,
            "size_bytes": result.size_bytes,
        }
    except WorkspaceError as exc:
        return _error(exc)


@tool
async def replace_file(
    path: str,
    old: str,
    new: str,
    expected_sha256: str,
    runtime: ToolRuntime[LoomContext],
) -> dict:
    """审批后替换已有 UTF-8 文件中唯一一段文本；执行前会复核旧 SHA-256。"""
    arguments = {
        "path": path,
        "old": old,
        "new": new,
        "expected_sha256": expected_sha256,
    }
    try:
        if runtime.context.approvals is None:
            raise ApprovalError("当前运行环境没有审批服务")
        await runtime.context.approvals.authorize_replace(
            thread_id=runtime.context.thread_id,
            run_id=runtime.context.run_id,
            tool_call_id=runtime.tool_call_id or "missing-tool-call-id",
            arguments=arguments,
        )
        result = await asyncio.to_thread(
            runtime.context.workspace.replace_text,
            runtime.context.thread_id,
            path,
            old=old,
            new=new,
            expected_sha256=expected_sha256,
        )
        return {
            "ok": True,
            "path": result.virtual_path,
            "sha256": result.sha256,
            "size_bytes": result.size_bytes,
        }
    except (WorkspaceError, ApprovalError) as exc:
        return _error(exc)


@tool
async def present_files(filepaths: list[str], runtime: ToolRuntime[LoomContext]) -> Command:
    """把 outputs 中已经完整写好的文件捕获为不可变、可下载的产物。"""
    tool_call_id = runtime.tool_call_id or "missing-tool-call-id"
    try:
        records = await runtime.context.artifacts.register_outputs(
            runtime.context.thread_id,
            runtime.context.run_id,
            filepaths,
        )
    except (WorkspaceError, ArtifactError) as exc:
        message = ToolMessage(
            content=json.dumps(_error(exc), ensure_ascii=False),
            tool_call_id=tool_call_id,
            name="present_files",
            status="error",
        )
        return Command(update={"messages": [message]})

    artifact_ids = [record.id for record in records]
    message = ToolMessage(
        content=json.dumps(
            {
                "ok": True,
                "artifacts": [
                    {
                        "id": record.id,
                        "display_name": record.display_name,
                        "sha256": record.sha256,
                        "size_bytes": record.size_bytes,
                    }
                    for record in records
                ],
            },
            ensure_ascii=False,
        ),
        tool_call_id=tool_call_id,
        name="present_files",
    )
    return Command(update={"messages": [message], "artifact_ids": artifact_ids})


FILE_TOOLS = [list_dir, read_file, write_file, replace_file, present_files]
