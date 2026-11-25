"""SQLite engine + session factory. Schema is created on startup."""
from __future__ import annotations

import os
from collections.abc import Iterator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


def _ensure_sqlite_dir(url: str) -> None:
    # sqlite:////data/app.db -> /data/app.db ; sqlite:///./app.db -> ./app.db
    if url.startswith("sqlite:///") and ":memory:" not in url:
        path = url[len("sqlite:///"):]
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)


def make_engine(url: str):
    _ensure_sqlite_dir(url)
    eng = create_engine(url, connect_args={"check_same_thread": False}, future=True)

    @event.listens_for(eng, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - trivial
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()

    return eng


engine = make_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    from . import models  # noqa: F401  (register tables)

    Base.metadata.create_all(engine)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def db_is_reachable() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
