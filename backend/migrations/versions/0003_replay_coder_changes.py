"""add safe replay and coder change proposals

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLite 无法原地修改匿名 CHECK；先复制审批表以加入 coder_change 类型。
    op.rename_table("approvals", "approvals_0002")
    op.create_table(
        "approvals",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("run_id", sa.Text(), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("suspend_key", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("payload_hash", sa.Text(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("checkpoint_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("response_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("resolved_at", sa.Text(), nullable=True),
        sa.Column("consumed_at", sa.Text(), nullable=True),
        sa.UniqueConstraint("run_id", "suspend_key"),
        sa.CheckConstraint("kind IN ('tool_batch','clarification','coder_change')"),
        sa.CheckConstraint("json_valid(payload_json)"),
        sa.CheckConstraint("status IN ('pending','approved','rejected','answered','expired')"),
        sa.CheckConstraint("response_json IS NULL OR json_valid(response_json)"),
        sa.CheckConstraint(
            "(status = 'pending' AND resolved_at IS NULL) OR (status <> 'pending' AND resolved_at IS NOT NULL)"
        ),
        sa.CheckConstraint(
            "status NOT IN ('approved','rejected','answered') OR "
            "(checkpoint_id IS NOT NULL AND response_json IS NOT NULL)"
        ),
        sa.CheckConstraint("kind <> 'tool_batch' OR status <> 'answered'"),
        sa.CheckConstraint("kind <> 'clarification' OR status NOT IN ('approved','rejected')"),
        sa.CheckConstraint("consumed_at IS NULL OR status IN ('approved','rejected','answered')"),
    )
    op.execute(
        "INSERT INTO approvals SELECT id,run_id,suspend_key,kind,payload_hash,payload_json,checkpoint_id,"
        "status,response_json,created_at,resolved_at,consumed_at FROM approvals_0002"
    )
    op.drop_table("approvals_0002")
    op.create_index("ix_approvals_pending", "approvals", ["run_id", "status"])
    op.create_table(
        "run_replays",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("source_run_id", sa.Text(), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("evidence_hash", sa.Text(), nullable=False),
        sa.Column("evidence_json", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="completed"),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.UniqueConstraint("source_run_id", "evidence_hash"),
        sa.CheckConstraint("status = 'completed'"),
        sa.CheckConstraint("json_valid(evidence_json)"),
    )
    op.create_table(
        "coder_change_proposals",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("task_id", sa.Text(), sa.ForeignKey("subagent_tasks.id"), nullable=False),
        sa.Column("run_id", sa.Text(), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("thread_id", sa.Text(), sa.ForeignKey("threads.id"), nullable=False),
        sa.Column("approval_id", sa.Text(), sa.ForeignKey("approvals.id"), nullable=False, unique=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("manifest_hash", sa.Text(), nullable=False),
        sa.Column("manifest_json", sa.Text(), nullable=False),
        sa.Column("verification_json", sa.Text(), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("resolved_at", sa.Text(), nullable=True),
        sa.UniqueConstraint("task_id", "manifest_hash"),
        sa.CheckConstraint("status IN ('pending','rejected','verifying','accepted','failed','conflict')"),
        sa.CheckConstraint("json_valid(manifest_json)"),
        sa.CheckConstraint("verification_json IS NULL OR json_valid(verification_json)"),
    )


def downgrade() -> None:
    op.drop_table("coder_change_proposals")
    op.drop_table("run_replays")
    # 降级只在不存在 coder_change 行时有意义；开发期迁移明确失败优于丢审批。
    op.execute("DELETE FROM approvals WHERE kind = 'coder_change'")
    op.rename_table("approvals", "approvals_0003")
    op.create_table(
        "approvals",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("run_id", sa.Text(), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("suspend_key", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("payload_hash", sa.Text(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("checkpoint_id", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("response_json", sa.Text()),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("resolved_at", sa.Text()),
        sa.Column("consumed_at", sa.Text()),
        sa.UniqueConstraint("run_id", "suspend_key"),
        sa.CheckConstraint("kind IN ('tool_batch','clarification')"),
        sa.CheckConstraint("json_valid(payload_json)"),
        sa.CheckConstraint("status IN ('pending','approved','rejected','answered','expired')"),
        sa.CheckConstraint("response_json IS NULL OR json_valid(response_json)"),
        sa.CheckConstraint(
            "(status = 'pending' AND resolved_at IS NULL) OR (status <> 'pending' AND resolved_at IS NOT NULL)"
        ),
        sa.CheckConstraint(
            "status NOT IN ('approved','rejected','answered') "
            "OR (checkpoint_id IS NOT NULL AND response_json IS NOT NULL)"
        ),
        sa.CheckConstraint("kind <> 'tool_batch' OR status <> 'answered'"),
        sa.CheckConstraint("kind <> 'clarification' OR status NOT IN ('approved','rejected')"),
        sa.CheckConstraint("consumed_at IS NULL OR status IN ('approved','rejected','answered')"),
    )
    op.execute("INSERT INTO approvals SELECT * FROM approvals_0003")
    op.drop_table("approvals_0003")
    op.create_index("ix_approvals_pending", "approvals", ["run_id", "status"])
