"""当前 HTTP API 的请求 DTO。"""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CreateThread(BaseModel):
    profile: str = "default"
    title: str = "New thread"


class SubmitRun(BaseModel):
    text: str = Field(min_length=1)
    attachment_ids: list[str] = Field(default_factory=list, max_length=20)
    client_request_id: UUID


class ResolveApproval(BaseModel):
    """客户端只能选择批准或拒绝，不能提交替换后的工具参数。"""

    model_config = ConfigDict(extra="forbid")

    payload_hash: str = Field(min_length=64, max_length=64)
    decision: Literal["approve", "reject"]
    reason: str | None = Field(default=None, max_length=1000)


class FileEvidence(BaseModel):
    """服务端应重新读取并核对的文件事实。"""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=1000)
    sha256: str = Field(min_length=64, max_length=64)


class ResolveToolExecution(BaseModel):
    """uncertain 结果只能放弃，或用已声明文件的精确 hash 证明完成。"""

    model_config = ConfigDict(extra="forbid")

    action: Literal["skip", "verify"]
    evidence: list[FileEvidence] = Field(default_factory=list, max_length=20)


class CreateMemory(BaseModel):
    """用户通过 API 明确保存一条偏好。"""

    model_config = ConfigDict(extra="forbid")

    category: Literal["preference"] = "preference"
    memory_key: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    content: str = Field(min_length=1, max_length=2000)


class UpdateMemory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=2000)
    expected_version: int = Field(ge=1)


class DeleteMemory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
