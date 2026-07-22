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


def _add_missing_columns():
    """No Alembic in this project (create_all only creates missing tables,
    never alters existing ones) - this is the lightweight stand-in for the
    one column added after llm_signal_cache already existed in a deployed
    database. ADD COLUMN is supported the same way by SQLite and Postgres,
    the only two engines this app targets."""
    inspector = inspect(engine)
    if "llm_signal_cache" not in inspector.get_table_names():
        return
    existing_columns = {c["name"] for c in inspector.get_columns("llm_signal_cache")}
    if "universe_json" not in existing_columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE llm_signal_cache ADD COLUMN universe_json TEXT"))
