"""Alembic migration and async SQLAlchemy session setup."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import event
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def migrate_database(path: Path) -> None:
    """Upgrade one app.sqlite file; never use ORM ``create_all``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    backend_root = Path(__file__).resolve().parents[3]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", URL.create("sqlite", database=str(path)).render_as_string())
    command.upgrade(config, "head")


def create_sessionmaker(path: Path) -> async_sessionmaker:
    """Create independent AsyncSession instances with required SQLite pragmas."""
    engine = create_async_engine(URL.create("sqlite+aiosqlite", database=str(path)))

    @event.listens_for(engine.sync_engine, "connect")
    def configure_sqlite(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    return async_sessionmaker(engine, expire_on_commit=False)
