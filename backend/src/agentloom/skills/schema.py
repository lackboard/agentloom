"""Skill 元数据与不可变运行快照。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SkillMetadata(BaseModel):
    """启动扫描得到的轻量信息；这里不包含 Skill 正文。"""

    model_config = ConfigDict(frozen=True)

    name: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    description: str = Field(min_length=1, max_length=500)
    allowed_tools: tuple[str, ...]


class SkillSnapshot(SkillMetadata):
    """某次 Run 已加载的完整 Skill；内容和权限随 hash 一起冻结。"""

    content: str
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot_ref: str
    activation: Literal["slash", "tool"]
    run_id: str

    def to_state(self) -> dict:
        """转换为 checkpoint 可直接序列化的普通数据。"""
        return self.model_dump(mode="json")
