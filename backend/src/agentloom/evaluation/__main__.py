"""`python -m agentloom.evaluation` 命令入口。"""

import argparse
import hashlib
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from agentloom.config import load_config
from agentloom.evaluation.grading import summarize_results
from agentloom.evaluation.report import render_markdown
from agentloom.evaluation.runner import EvaluationRunner, write_json_report
from agentloom.evaluation.schema import load_tasks


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="运行 AgentLoom 固定任务评测")
    parser.add_argument("--tasks", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--expected-count", type=int)
    parser.add_argument("--require-live", action="store_true")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--timeout", type=float, default=240.0)
    parser.add_argument(
        "--ids",
        help="只运行逗号分隔的任务 ID；用于先验证评测链路，不改变原任务定义",
    )
    return parser.parse_args()


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    if args.repeat < 1:
        raise SystemExit("--repeat 必须大于 0")
    config = load_config()
    selected = config.models.default
    if args.require_live and selected.provider == "fake":
        print("EVALUATION: NOT_RUN（当前 provider=fake）")
        return 2
    tasks = load_tasks(args.tasks, expected_count=args.expected_count)
    if args.ids:
        selected_ids = {item.strip() for item in args.ids.split(",") if item.strip()}
        tasks = [task for task in tasks if task.id in selected_ids]
        missing = selected_ids - {task.id for task in tasks}
        if missing:
            raise SystemExit(f"--ids 包含未知任务：{', '.join(sorted(missing))}")
        if not tasks:
            raise SystemExit("--ids 没有选中任务")
    temporary = None
    if args.data_dir is None:
        temporary = tempfile.TemporaryDirectory(prefix="agentloom-evaluation-")
        data_dir = Path(temporary.name)
    else:
        data_dir = args.data_dir
    try:
        runner = EvaluationRunner(config=config, data_dir=data_dir, timeout_seconds=args.timeout)
        results = runner.run(tasks, repeat=args.repeat)
    finally:
        if temporary is not None:
            temporary.cleanup()
    summary = summarize_results(results)
    metadata = {
        "provider": selected.provider,
        "model": selected.model,
        "generated_at": datetime.now(UTC).isoformat(),
        "tasks_file": str(args.tasks),
        "task_set_sha256": hashlib.sha256(args.tasks.read_bytes()).hexdigest(),
        "repeat": args.repeat,
        "selected_ids": [task.id for task in tasks],
        "temperature": selected.temperature,
        "budgets": {
            "model_attempts": config.runtime.max_model_attempts_per_run,
            "tool_executions": config.runtime.max_tool_executions_per_run,
            "subagents": config.runtime.max_subagents_per_run,
        },
        "mcp_enabled": config.mcp.enabled,
    }
    write_json_report(args.output, metadata=metadata, results=results, summary=summary)
    markdown = render_markdown(title="AgentLoom 评测报告", metadata=metadata, summary=summary, results=results)
    args.output.with_suffix(".md").write_text(markdown, encoding="utf-8")
    print(markdown)
    return 1 if summary["outcomes"].get("error", 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())
