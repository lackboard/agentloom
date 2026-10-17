"""M6 评测定义与评分只测试确定性规则，不调用模型。"""

import json
from collections import Counter
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from agentloom.evaluation.grading import grade_observation, summarize_results
from agentloom.evaluation.report import render_markdown
from agentloom.evaluation.schema import ArtifactObservation, EvaluationTask, Observation, load_tasks
from agentloom.runtime.projection import project_graph_messages

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _observation(**overrides) -> Observation:
    values = {
        "run_id": "run-1",
        "status": "succeeded",
        "final_text": "答案是 42，报告已经生成。",
        "tool_names": ["add", "present_files", "task"],
        "proposed_tool_calls": 3,
        "admitted_tool_calls": 3,
        "artifact_items": [ArtifactObservation(name="report.md", kind="output", content="# 报告\n42")],
        "subagent_count": 1,
        "wall_seconds": 2.0,
        "approval_wait_seconds": 0.5,
        "model_attempts": 2,
        "tool_executions": 3,
        "input_tokens": 100,
        "output_tokens": 20,
        "usage_complete": True,
    }
    values.update(overrides)
    return Observation.model_validate(values)


def _task(*, manual_review: str | None = None, variant: str | None = None) -> EvaluationTask:
    payload = {
        "id": "CP-01" if variant else "FC-01",
        "category": "comparison" if variant else "file_code",
        "prompt": "完成固定任务",
        "acceptance": {
            "final_contains_all": ["42"],
            "tools_all": ["add", "present_files", "task"],
            "artifact": {"name": "report.md", "contains_all": ["42"]},
            "subagents_min": 1,
            "manual_review": manual_review,
        },
    }
    if variant:
        payload.update({"variant": variant, "pair_id": "pair-1"})
    return EvaluationTask.model_validate(payload)


def test_fixed_task_set_is_predeclared_and_has_required_distribution():
    tasks = load_tasks(PROJECT_ROOT / "backend/evaluations/fixed_tasks.json", expected_count=30)

    assert Counter(task.category for task in tasks) == {
        "file_code": 10,
        "data": 8,
        "retrieval": 6,
        "delegation": 6,
    }
    assert all(task.acceptance.model_dump(exclude_none=True) for task in tasks)


def test_real_provider_content_blocks_are_projected_to_text_and_blocks():
    message = AIMessage(content=[{"type": "text", "text": "最终答案：42"}])

    projected = project_graph_messages("run-1", [message])

    assert projected[0].content["text"] == "最终答案：42"
    assert projected[0].content["blocks"] == [{"type": "text", "text": "最终答案：42"}]


def test_task_loader_rejects_duplicate_ids(tmp_path: Path):
    task = _task().model_dump(mode="json")
    path = tmp_path / "duplicates.json"
    path.write_text(json.dumps([task, task]), encoding="utf-8")

    with pytest.raises(ValueError, match="不能重复"):
        load_tasks(path)


def test_grader_checks_real_observation_and_retains_manual_review():
    passed = grade_observation(_task(), _observation())
    pending = grade_observation(_task(manual_review="检查报告结构"), _observation())
    failed = grade_observation(_task(), _observation(tool_names=["add", "task"]))

    assert passed.outcome == "passed"
    assert pending.outcome == "manual_review"
    assert pending.checks[-1].name == "manual_review"
    assert pending.checks[-1].passed is False
    assert failed.outcome == "failed"
    assert any(check.name == "tool_used:present_files" and not check.passed for check in failed.checks)


def test_summary_keeps_failures_and_computes_controlled_comparison():
    single_task = _task(variant="single")
    multi_task = EvaluationTask.model_validate(
        {**single_task.model_dump(mode="json"), "id": "CP-02", "variant": "multi"}
    )
    results = [
        grade_observation(single_task, _observation(wall_seconds=2.0), repetition=1),
        grade_observation(single_task, _observation(wall_seconds=4.0), repetition=2),
        grade_observation(multi_task, _observation(status="failed", wall_seconds=8.0), repetition=1),
    ]

    summary = summarize_results(results)
    markdown = render_markdown(
        title="test",
        metadata={"provider": "fake", "model": "fixed", "generated_at": "now"},
        summary=summary,
        results=results,
    )

    assert summary["outcomes"] == {"passed": 2, "failed": 1}
    assert summary["automatic_completion_rate"] == pytest.approx(2 / 3)
    assert summary["active_seconds_total"] == pytest.approx(12.5)
    assert summary["variants"]["single"]["wall_seconds_mean"] == 3.0
    assert summary["variants"]["single"]["wall_seconds_pstdev"] == 1.0
    assert "CP-02#1" in markdown
    assert "run_status" in markdown
