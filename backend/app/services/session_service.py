"""Conversation persistence in SQLite."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ChatSession, Message


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def get_history(db: Session, session_id: str) -> list[Message]:
    stmt = select(Message).where(Message.session_id == session_id).order_by(Message.id.asc())
    return list(db.scalars(stmt))


def history_as_llm_messages(rows: list[Message]) -> list[dict]:
    return [{"role": r.role, "content": r.content} for r in rows]


def get_system_prompt(db: Session, session_id: str) -> str | None:
    row = db.get(ChatSession, session_id)
    return row.system_prompt if row else None


def save_exchange(
    db: Session,
    session_id: str,
    user_text: str,
    assistant_text: str,
    metadata: dict,
    system_prompt: str | None,
) -> None:
    """Write the user + assistant pair atomically. Called only after success."""
    try:
        now = _now()
        session_row = db.get(ChatSession, session_id)
        if session_row is None:
            db.add(ChatSession(session_id=session_id, system_prompt=system_prompt, created_at=now))
        elif system_prompt is not None and system_prompt != session_row.system_prompt:
            session_row.system_prompt = system_prompt
        db.add(Message(session_id=session_id, role="user", content=user_text, meta=None, created_at=now))
        db.add(
            Message(
                session_id=session_id,
                role="assistant",
                content=assistant_text,
                meta=json.dumps(metadata),
                created_at=_now(),
            )
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
