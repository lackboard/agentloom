import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import URL

from agentloom.persistence.database import migrate_database
from agentloom.persistence.models import Base


def test_alembic_baseline_matches_design_and_preserves_data(tmp_path) -> None:
    app_path = tmp_path / "app.sqlite"
    migrate_database(app_path)
    migrated = sqlite3.connect(app_path)
    design = sqlite3.connect(":memory:")
    design.executescript((Path(__file__).resolve().parents[2] / "schema.sql").read_text(encoding="utf-8"))

    def table_names(connection):
        return {
            name
            for (name,) in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' AND name != 'alembic_version'"
            )
        }

    def columns(connection, table):
        return sorted(
            (row[1], row[2], row[3], row[4], row[5]) for row in connection.execute(f"PRAGMA table_info({table})")
        )

    def indexes(connection):
        return {
            name: (bool(unique), [row[2] for row in connection.execute(f"PRAGMA index_info({name})")])
            for name, unique in connection.execute(
                "SELECT name, CASE WHEN sql LIKE 'CREATE UNIQUE INDEX%' THEN 1 ELSE 0 END "
                "FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
            )
        }

    assert table_names(migrated) == table_names(design)
    assert len(table_names(migrated)) == 12
    for table in table_names(design):
        assert columns(migrated, table) == columns(design, table)
    assert indexes(migrated) == indexes(design)
    assert set(Base.metadata.tables) == {
        "threads",
        "runs",
        "messages",
        "run_events",
        "trace_spans",
        "run_replays",
        "tool_executions",
        "approvals",
        "subagent_tasks",
        "coder_change_proposals",
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
        assert reopened.execute("SELECT version_num FROM alembic_version").fetchone() == ("0003",)


def test_m7_migration_backfills_existing_run_and_preserves_checks(tmp_path) -> None:
    app_path = tmp_path / "legacy.sqlite"
    backend_root = Path(__file__).resolve().parents[1]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", URL.create("sqlite", database=str(app_path)).render_as_string())
    command.upgrade(config, "0001")

    with sqlite3.connect(app_path) as connection:
        connection.execute(
            "INSERT INTO threads(id,title,agent_profile,created_at,updated_at) "
            "VALUES ('t1','one','default','now','now')"
        )
        connection.execute(
            """INSERT INTO runs(
                id,thread_id,client_request_id,request_hash,input_json,input_message_id,status,
                model_name,config_snapshot_json,budget_json,created_at
            ) VALUES ('r1','t1','c1','hash','{}','m1','pending','fake','{}','{}','now')"""
        )
        connection.commit()

    migrate_database(app_path)
    with sqlite3.connect(app_path) as connection:
        assert connection.execute("SELECT trace_id,status FROM runs WHERE id='r1'").fetchone() == (
            "r1",
            "pending",
        )
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("0003",)
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE runs SET status='unknown' WHERE id='r1'")
