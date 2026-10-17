"""add durable runtime tracing

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 旧 Run 使用自身 UUID 回填 trace_id，升级过程中不丢历史业务数据。
    with op.batch_alter_table("runs") as batch:
        batch.add_column(sa.Column("trace_id", sa.Text(), nullable=True))
    op.execute("UPDATE runs SET trace_id = id WHERE trace_id IS NULL")
    runs_checks = (
        sa.CheckConstraint("json_valid(input_json)"),
        sa.CheckConstraint(
            "status IN ('pending','running','waiting_input','interrupted','cancelling',"
            "'succeeded','failed','cancelled')"
        ),
        sa.CheckConstraint("json_valid(config_snapshot_json)"),
        sa.CheckConstraint("json_valid(budget_json)"),
        sa.CheckConstraint("model_attempts >= 0"),
        sa.CheckConstraint("tool_executions_count >= 0"),
        sa.CheckConstraint("input_tokens >= 0"),
        sa.CheckConstraint("output_tokens >= 0"),
        sa.CheckConstraint("usage_complete IN (0,1)"),
        sa.CheckConstraint("estimated_cost_usd IS NULL OR estimated_cost_usd >= 0"),
        sa.CheckConstraint("next_event_seq > 0"),
        sa.CheckConstraint(
            "(status IN ('succeeded','failed','cancelled') AND finished_at IS NOT NULL) OR "
            "(status NOT IN ('succeeded','failed','cancelled') AND finished_at IS NULL)"
        ),
    )
    with op.batch_alter_table("runs", table_args=runs_checks) as batch:
        batch.alter_column("trace_id", existing_type=sa.Text(), nullable=False)
        batch.create_unique_constraint("uq_runs_trace_id", ["trace_id"])

    op.create_table(
        "trace_spans",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("trace_id", sa.Text(), nullable=False),
        sa.Column("run_id", sa.Text(), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("parent_span_id", sa.Text(), sa.ForeignKey("trace_spans.id"), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="running"),
        sa.Column("attributes_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("started_at", sa.Text(), nullable=False),
        sa.Column("finished_at", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.CheckConstraint("kind IN ('run','model','tool')"),
        sa.CheckConstraint("status IN ('running','waiting_input','succeeded','failed','cancelled')"),
        sa.CheckConstraint("json_valid(attributes_json)"),
        sa.CheckConstraint("duration_ms IS NULL OR duration_ms >= 0"),
        sa.CheckConstraint(
            "(status IN ('succeeded','failed','cancelled') AND finished_at IS NOT NULL) OR "
            "(status IN ('running','waiting_input') AND finished_at IS NULL)"
        ),
    )
    op.create_index("ix_trace_spans_run_started", "trace_spans", ["run_id", "started_at"])
    op.create_index("ix_trace_spans_trace", "trace_spans", ["trace_id"])


def downgrade() -> None:
    op.drop_index("ix_trace_spans_trace", table_name="trace_spans")
    op.drop_index("ix_trace_spans_run_started", table_name="trace_spans")
    op.drop_table("trace_spans")
    with op.batch_alter_table("runs") as batch:
        batch.drop_constraint("uq_runs_trace_id", type_="unique")
        batch.drop_column("trace_id")
