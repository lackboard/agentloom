"""固定任务、运行观察和评测结果的数据契约。"""

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AttachmentFixture(StrictModel):
    name: str = Field(min_length=1)
    content: str
    mime_type: str = "text/plain"


class ArtifactExpectation(StrictModel):
    name: str
    contains_all: list[str] = Field(default_factory=list)


class AcceptanceSpec(StrictModel):
    """在模型运行前声明的验收条件，不能看完输出后再改答案。"""

    final_contains_all: list[str] = Field(default_factory=list)
    final_contains_any: list[str] = Field(default_factory=list)
    tools_all: list[str] = Field(default_factory=list)
    artifact: ArtifactExpectation | None = None
    subagents_min: int = Field(default=0, ge=0)
    manual_review: str | None = None


class EvaluationTask(StrictModel):
    id: str = Field(pattern=r"^[A-Z][A-Z0-9]+-[0-9]{2}$")
    category: Literal["file_code", "data", "retrieval", "delegation", "comparison"]
    prompt: str = Field(min_length=1)
    attachments: list[AttachmentFixture] = Field(default_factory=list)
    acceptance: AcceptanceSpec
    variant: Literal["single", "multi"] | None = None
    pair_id: str | None = None

    @model_validator(mode="after")
    def validate_comparison_pair(self):
        if self.category == "comparison" and (self.variant is None or self.pair_id is None):
            raise ValueError("comparison 任务必须提供 variant 和 pair_id")
        if self.category != "comparison" and (self.variant is not None or self.pair_id is not None):
            raise ValueError("只有 comparison 任务可以提供 variant/pair_id")
        return self


class ArtifactObservation(StrictModel):
    name: str
    kind: str
    content: str | None = None


class Observation(StrictModel):
    run_id: str
    status: str
    final_text: str
    tool_names: list[str]
    proposed_tool_calls: int
    admitted_tool_calls: int
    artifact_items: list[ArtifactObservation]
    subagent_count: int
    wall_seconds: float
    approval_wait_seconds: float
    model_attempts: int
    tool_executions: int
    input_tokens: int
    output_tokens: int
    usage_complete: bool
    error: dict | None = None


class CheckResult(StrictModel):
    name: str
    passed: bool
    detail: str


class TaskResult(StrictModel):
    task_id: str
    category: str
    repetition: int = Field(ge=1)
    variant: str | None = None
    pair_id: str | None = None
    outcome: Literal["passed", "failed", "manual_review", "error"]
    checks: list[CheckResult]
    observation: Observation | None = None
    runner_error: str | None = None


def load_tasks(path: Path, *, expected_count: int | None = None) -> list[EvaluationTask]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("评测任务文件顶层必须是数组")
    tasks = [EvaluationTask.model_validate(item) for item in raw]
    identifiers = [task.id for task in tasks]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("评测任务 ID 不能重复")
    if expected_count is not None and len(tasks) != expected_count:
        raise ValueError(f"固定任务必须恰好为 {expected_count} 项，实际为 {len(tasks)}")
    return tasks
