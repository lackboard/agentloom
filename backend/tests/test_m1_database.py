import sqlite3
from pathlib import Path

from agentloom.persistence.database import migrate_database
from agentloom.persistence.models import Base


def test_alembic_baseline_matches_design_and_preserves_data(tmp_path) -> None:
    app_path = tmp_path / "app.sqlite"
    migrate_database(app_path)
    migrated = sqlite3.connect(app_path)
    design = sqlite3.connect(":memory:")
    design.executescript((Path(__file__).resolve().parents[2] / "schema.sql").read_text(encoding="utf-8"))

    def schema(connection):
        return {
            (kind, name): " ".join(
                "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--")).split()
            )
            for kind, name, sql in connection.execute(
                "SELECT type, name, sql FROM sqlite_master WHERE type IN ('table','index') "
                "AND name NOT LIKE 'sqlite_%' AND name != 'alembic_version' AND sql IS NOT NULL"
            )
        }

    assert schema(migrated) == schema(design)
    assert len([key for key in schema(migrated) if key[0] == "table"]) == 9
    assert set(Base.metadata.tables) == {
        "threads",
        "runs",
        "messages",
        "run_events",
        "tool_executions",
        "approvals",
        "subagent_tasks",
        "artifacts",
        "memories",
    }
    assert all(column.comment for table in Base.metadata.tables.values() for column in table.columns)
    assert migrated.execute("PRAGMA foreign_key_check").fetchall() == []
    migrated.execute(
        "INSERT INTO threads(id,title,agent_profile,created_at,updated_at) VALUES ('t1','one','default','now','now')"
    )
    migrated.commit()
    migrated.close()
    design.close()

    migrate_database(app_path)
    with sqlite3.connect(app_path) as reopened:
        assert reopened.execute("SELECT title FROM threads WHERE id='t1'").fetchone() == ("one",)
        assert reopened.execute("SELECT version_num FROM alembic_version").fetchone() == ("0001",)
