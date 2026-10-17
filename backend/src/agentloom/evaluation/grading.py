"""只依据预注册条件评分，不让模型自己宣称任务通过。"""

from collections import Counter, defaultdict
from statistics import fmean, pstdev

from agentloom.evaluation.schema import CheckResult, EvaluationTask, Observation, TaskResult


def _contains(text: str, expected: str) -> bool:
    return expected.casefold() in text.casefold()


def grade_observation(task: EvaluationTask, observation: Observation, *, repetition: int = 1) -> TaskResult:
    checks = [
        CheckResult(
            name="run_status",
            passed=observation.status == "succeeded",
            detail=f"expected=succeeded actual={observation.status}",
        )
    ]
    for value in task.acceptance.final_contains_all:
        checks.append(
            CheckResult(
                name=f"final_contains:{value}",
                passed=_contains(observation.final_text, value),
                detail=f"最终回答应包含 {value!r}",
            )
        )
    if task.acceptance.final_contains_any:
        passed = any(_contains(observation.final_text, value) for value in task.acceptance.final_contains_any)
        checks.append(
            CheckResult(
                name="final_contains_any",
                passed=passed,
                detail=f"最终回答应至少包含一个：{task.acceptance.final_contains_any}",
            )
        )
    tool_set = set(observation.tool_names)
    for tool_name in task.acceptance.tools_all:
        checks.append(
            CheckResult(
                name=f"tool_used:{tool_name}",
                passed=tool_name in tool_set,
                detail=f"实际工具：{observation.tool_names}",
            )
        )
    if task.acceptance.subagents_min:
        checks.append(
            CheckResult(
                name="subagents_min",
                passed=observation.subagent_count >= task.acceptance.subagents_min,
                detail=f"expected>={task.acceptance.subagents_min} actual={observation.subagent_count}",
            )
        )
    expected_artifact = task.acceptance.artifact
    if expected_artifact is not None:
        artifact = next((item for item in observation.artifact_items if item.name == expected_artifact.name), None)
        checks.append(
            CheckResult(
                name=f"artifact_exists:{expected_artifact.name}",
                passed=artifact is not None,
                detail=f"实际产物：{[item.name for item in observation.artifact_items]}",
            )
        )
        for value in expected_artifact.contains_all:
            checks.append(
                CheckResult(
                    name=f"artifact_contains:{value}",
                    passed=artifact is not None and artifact.content is not None and _contains(artifact.content, value),
                    detail=f"产物 {expected_artifact.name} 应包含 {value!r}",
                )
            )

    automated_pass = all(check.passed for check in checks)
    if not automated_pass:
        outcome = "failed"
    elif task.acceptance.manual_review:
        outcome = "manual_review"
        checks.append(CheckResult(name="manual_review", passed=False, detail=task.acceptance.manual_review))
    else:
        outcome = "passed"
    return TaskResult(
        task_id=task.id,
        category=task.category,
        repetition=repetition,
        variant=task.variant,
        pair_id=task.pair_id,
        outcome=outcome,
        checks=checks,
        observation=observation,
    )


def summarize_results(results: list[TaskResult]) -> dict:
    counts = Counter(result.outcome for result in results)
    observations = [result.observation for result in results if result.observation is not None]
    task_count = len(results)
    auto_pass = counts["passed"]
    pending_manual = counts["manual_review"]
    artifact_required = [
        result for result in results if any(check.name.startswith("artifact_exists:") for check in result.checks)
    ]
    artifact_passed = sum(
        all(check.passed for check in result.checks if check.name.startswith("artifact_"))
        for result in artifact_required
    )
    proposed = sum(item.proposed_tool_calls for item in observations)
    admitted = sum(item.admitted_tool_calls for item in observations)
    summary = {
        "runs": task_count,
        "outcomes": dict(counts),
        "automatic_completion_rate": auto_pass / task_count if task_count else 0.0,
        "completion_upper_bound_with_manual_review": (auto_pass + pending_manual) / task_count if task_count else 0.0,
        "artifact_delivery_rate": artifact_passed / len(artifact_required) if artifact_required else None,
        "tool_admission_rate": admitted / proposed if proposed else None,
        "wall_seconds_total": sum(item.wall_seconds for item in observations),
        "approval_wait_seconds_total": sum(item.approval_wait_seconds for item in observations),
        "active_seconds_total": sum(max(0.0, item.wall_seconds - item.approval_wait_seconds) for item in observations),
        "input_tokens": sum(item.input_tokens for item in observations),
        "output_tokens": sum(item.output_tokens for item in observations),
        "usage_complete": all(item.usage_complete for item in observations),
    }
    variants: dict[str, list[TaskResult]] = defaultdict(list)
    for result in results:
        if result.variant is not None:
            variants[result.variant].append(result)
    if variants:
        summary["variants"] = {}
        for name, rows in variants.items():
            durations = [row.observation.wall_seconds for row in rows if row.observation is not None]
            active_durations = [
                max(0.0, row.observation.wall_seconds - row.observation.approval_wait_seconds)
                for row in rows
                if row.observation is not None
            ]
            tokens = [
                row.observation.input_tokens + row.observation.output_tokens
                for row in rows
                if row.observation is not None
            ]
            summary["variants"][name] = {
                "runs": len(rows),
                "completion_rate": sum(row.outcome == "passed" for row in rows) / len(rows),
                "wall_seconds_mean": fmean(durations) if durations else None,
                "wall_seconds_pstdev": pstdev(durations) if len(durations) > 1 else 0.0,
                "active_seconds_mean": fmean(active_durations) if active_durations else None,
                "active_seconds_pstdev": pstdev(active_durations) if len(active_durations) > 1 else 0.0,
                "tokens_mean": fmean(tokens) if tokens else None,
                "tokens_pstdev": pstdev(tokens) if len(tokens) > 1 else 0.0,
            }
    return summary
