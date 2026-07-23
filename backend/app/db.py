from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, declarative_base

from app.config import settings

# Managed Postgres providers (Render, Heroku, Railway) commonly hand out
# "postgres://" URLs, but SQLAlchemy 2.x's default dialect requires
# "postgresql://" - normalize rather than requiring the user to edit it.
_database_url = settings.database_url
if _database_url.startswith("postgres://"):
    _database_url = _database_url.replace("postgres://", "postgresql://", 1)

connect_args = {"check_same_thread": False} if _database_url.startswith("sqlite") else {}
engine = create_engine(_database_url, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from app import models  # noqa: F401 - register models on Base before create_all
    Base.metadata.create_all(bind=engine)
    _add_missing_columns()


_MISSING_COLUMNS: list[tuple[str, str, str]] = [
    # (table, column, DDL type) - columns added after their table already
    # existed in a deployed database. No Alembic in this project (create_all
    # only creates missing tables, never alters existing ones), so this is
    # the lightweight stand-in - ADD COLUMN is supported the same way by
    # SQLite and Postgres, the only two engines this app targets.
    ("llm_signal_cache", "universe_json", "TEXT"),
    ("trades", "source_agent_id", "VARCHAR"),
]


def _add_missing_columns():
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    for table, column, ddl_type in _MISSING_COLUMNS:
        if table not in existing_tables:
            continue
        existing_columns = {c["name"] for c in inspector.get_columns(table)}
        if column not in existing_columns:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}"))
