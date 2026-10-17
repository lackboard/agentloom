"""Alembic environment for AgentLoom's application database only."""

from pathlib import Path

from alembic import context
from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool


def run_migrations() -> None:
    url = context.config.get_main_option("sqlalchemy.url")
    database = make_url(url).database
    if database and database != ":memory:":
        Path(database).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, poolclass=NullPool)

    @event.listens_for(engine, "connect")
    def configure_sqlite(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=None)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


run_migrations()
