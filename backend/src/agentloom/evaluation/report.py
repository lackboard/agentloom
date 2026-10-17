"""把机器可读评测结果转换为便于审查的 Markdown。"""

from agentloom.evaluation.schema import TaskResult


def _percent(value: float | None) -> str:
    return "N/A" if value is None else f"{value * 100:.1f}%"


def _number(value: float | None, *, suffix: str = "", digits: int = 2) -> str:
    return "N/A" if value is None else f"{value:.{digits}f}{suffix}"


def render_markdown(*, title: str, metadata: dict, summary: dict, results: list[TaskResult]) -> str:
    lines = [
        f"# {title}",
        "",
        f"- 模式：`{metadata['provider']}` / `{metadata['model']}`",
        f"- 生成时间：{metadata['generated_at']}",
        f"- 运行数：{summary['runs']}",
        f"- 自动完成率：{_percent(summary['automatic_completion_rate'])}",
        f"- 含待人工复核上界：{_percent(summary['completion_upper_bound_with_manual_review'])}",
        f"- 产物交付率：{_percent(summary['artifact_delivery_rate'])}",
        f"- 工具账本接纳率：{_percent(summary['tool_admission_rate'])}",
        f"- 总 wall time：{summary['wall_seconds_total']:.2f}s",
        f"- 人工等待时间：{summary['approval_wait_seconds_total']:.2f}s",
        f"- Agent 活跃时间：{summary['active_seconds_total']:.2f}s",
        (
            f"- Token：input={summary['input_tokens']} / output={summary['output_tokens']} / "
            f"complete={summary['usage_complete']}"
        ),
        "- 费用：N/A（配置未提供可审计的模型单价，不根据模型名猜测）",
        "",
    ]
    if "variants" in summary:
        lines.extend(
            [
                "## 对照",
                "",
                "| 配置 | 运行数 | 完成率 | 平均延迟 ± 标准差 | 平均 Token ± 标准差 |",
                "| --- | ---: | ---: | ---: | ---: |",
            ]
        )
        for name, values in summary["variants"].items():
            lines.append(
                f"| {name} | {values['runs']} | {_percent(values['completion_rate'])} | "
                f"{_number(values['wall_seconds_mean'])} ± {_number(values['wall_seconds_pstdev'], suffix='s')} | "
                f"{_number(values['tokens_mean'], digits=1)} ± {_number(values['tokens_pstdev'], digits=1)} |"
            )
        lines.append("")
    lines.extend(
        [
            "## 逐项结果",
            "",
            "| 任务 | 类别/配置 | 结果 | 延迟 | Token | 失败检查 |",
            "| --- | --- | --- | ---: | ---: | --- |",
        ]
    )
    for result in results:
        observation = result.observation
        failed = [check.name for check in result.checks if not check.passed]
        error = result.runner_error or ", ".join(failed) or "-"
        category = result.variant or result.category
        latency = "-" if observation is None else f"{observation.wall_seconds:.2f}s"
        tokens = "-" if observation is None else str(observation.input_tokens + observation.output_tokens)
        lines.append(
            f"| {result.task_id}#{result.repetition} | {category} | {result.outcome} | {latency} | {tokens} | {error} |"
        )
    lines.append("")
    return "\n".join(lines)
