"""
Database engine/session setup.

Uses SQLite for the MVP. Because SQLAlchemy is the access layer, switching
to PostgreSQL later is just a matter of changing DATABASE_URL in .env -
no application code needs to change.
"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

# SQLite needs this connect_arg when used from multiple threads (FastAPI
# runs endpoint handlers in a threadpool by default). It is a no-op for
# other database backends and is skipped automatically below.
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}

engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency that yields a DB session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables if they do not already exist and run lightweight schema migrations."""
    # Import models here so they are registered on Base.metadata before
    # create_all is called.
    from app import models  # noqa: F401
    from sqlalchemy import text

    Base.metadata.create_all(bind=engine)

    # Lightweight auto-migration for Phase 13 owner_id column on SQLite
    with engine.begin() as conn:
        try:
            conn.execute(text("ALTER TABLE models ADD COLUMN owner_id VARCHAR"))
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE deployments ADD COLUMN owner_id VARCHAR"))
        except Exception:
            pass
