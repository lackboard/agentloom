"""Lead 与子 Agent 之间的稳定数据契约。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AgentType = Literal["researcher", "coder"]
SubagentStatus = Literal["succeeded", "failed", "cancelled", "interrupted"]


class StrictContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SubagentRequest(StrictContract):
    """一次委派的最小输入；不包含父对话、密钥或可变 State。"""

    agent_type: AgentType
    prompt: str = Field(min_length=1, max_length=8000)
    expected_outputs: list[str] = Field(default_factory=list, max_length=10)
    input_files: list[str] = Field(default_factory=list, max_length=20)


class SubagentResult(StrictContract):
    """回到 Lead 的有界结果；内部消息不会穿透到父消息列表。"""

    task_id: str
    agent_type: AgentType
    status: SubagentStatus
    summary: str = Field(max_length=12000)
    artifact_ids: list[str] = Field(default_factory=list)
    sources: list[dict] = Field(default_factory=list)
    task_files: list[str] = Field(default_factory=list)
    requires_parent_action: dict | None = None
    acceptance: dict = Field(default_factory=lambda: {"tests_passed": "unverified"})
    error: dict | None = None

    def state_summary(self) -> dict:
        """只把恢复 Lead 所需的小摘要写进 checkpoint。"""
        return {
            "task_id": self.task_id,
            "agent_type": self.agent_type,
            "status": self.status,
            "summary": self.summary[:2000],
            "artifact_ids": self.artifact_ids,
            "task_files": self.task_files,
            "requires_parent_action": self.requires_parent_action,
        }
