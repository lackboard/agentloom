"""需要审批且只允许在 Docker 中执行的命令工具。"""

from langchain.tools import ToolRuntime, tool

from agentloom.runtime.approvals import ApprovalError
from agentloom.runtime.context import LoomContext
from agentloom.sandbox.docker import DockerSandboxError


@tool
async def bash(
    command: str,
    evidence_paths: list[str],
    runtime: ToolRuntime[LoomContext],
) -> dict:
    """在隔离 Docker 容器中运行 Bash；列出预期生成的 workspace/outputs 文件路径供恢复核验。"""
    arguments = {"command": command, "evidence_paths": evidence_paths}
    try:
        if len(command) > 10000:
            raise ApprovalError("Bash 命令超过 10000 字符限制")
        if runtime.context.docker is None or runtime.context.approvals is None:
            raise ApprovalError("当前运行环境没有 Docker 或审批服务")
        await runtime.context.approvals.authorize_bash(
            run_id=runtime.context.run_id,
            tool_call_id=runtime.tool_call_id or "missing-tool-call-id",
            arguments=arguments,
        )
        result = await runtime.context.docker.execute(
            thread_id=runtime.context.thread_id,
            run_id=runtime.context.run_id,
            tool_call_id=runtime.tool_call_id or "missing-tool-call-id",
            command=command,
        )
        if result.exit_code != 0:
            return {
                "ok": False,
                "error": {
                    "code": "BASH_EXIT_NONZERO",
                    "message": f"命令退出码为 {result.exit_code}",
                },
                "exit_code": result.exit_code,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "truncated": result.truncated,
            }
        return {
            "ok": True,
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "truncated": result.truncated,
            "evidence_paths": evidence_paths,
        }
    except (ApprovalError, DockerSandboxError) as exc:
        return {
            "ok": False,
            "error": {"code": getattr(exc, "code", "BASH_FAILED"), "message": str(exc)},
        }


COMMAND_TOOLS = [bash]
