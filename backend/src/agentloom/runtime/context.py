"""不进入 checkpoint 的单次 Run 服务端运行环境。"""

from dataclasses import dataclass
from typing import Any

from agentloom.artifacts import ArtifactService
from agentloom.runtime.approvals import ApprovalService
from agentloom.runtime.budget import RunBudgetController
from agentloom.runtime.ledger import ToolLedgerService
from agentloom.runtime.manager import RunManager
from agentloom.sandbox import WorkspaceService
from agentloom.sandbox.docker import DockerCommandService
from agentloom.skills import SkillLoader


@dataclass(frozen=True)
class LoomContext:
    """工具可使用的可信对象；由 RunExecutor 建立，模型不能提供。"""

    thread_id: str
    run_id: str
    workspace: WorkspaceService
    artifacts: ArtifactService
    ledger: ToolLedgerService | None = None
    approvals: ApprovalService | None = None
    docker: DockerCommandService | None = None
    skills: SkillLoader | None = None
    manager: RunManager | None = None
    # 避免把整个执行器结构暴露成工具参数 schema；运行时只由服务端注入。
    subagents: Any | None = None
    budget: RunBudgetController | None = None
    # 服务对象不参与模型工具参数 schema，避免 Pydantic 尝试解析其内部类型。
    memories: Any | None = None
