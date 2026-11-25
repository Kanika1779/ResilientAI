import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import HistoryMessage, HistoryResponse
from ..services import session_service

router = APIRouter()


@router.get("/sessions/{session_id}/messages", response_model=HistoryResponse)
def get_messages(session_id: str, db: Session = Depends(get_db)):
    rows = session_service.get_history(db, session_id)
    if not rows:
        raise HTTPException(status_code=404, detail="session not found")
    return HistoryResponse(
        session_id=session_id,
        messages=[
            HistoryMessage(
                role=r.role,
                content=r.content,
                created_at=r.created_at,
                metadata=json.loads(r.meta) if r.meta else None,
            )
            for r in rows
        ],
    )
