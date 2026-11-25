import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..schemas import ChatMetadata, ChatRequest, ChatResponse
from ..services import failure_sim, llm_service, session_service

router = APIRouter()
log = logging.getLogger("resilientai.chat")


@router.post("/chat", response_model=ChatResponse)
async def chat(body: ChatRequest, request: Request, db: Session = Depends(get_db)):
    started = time.perf_counter()  # monotonic

    simulation = None
    if settings.enable_failure_simulation:
        try:
            simulation = failure_sim.parse(request.headers.get(failure_sim.HEADER_NAME))
        except failure_sim.InvalidSimulationHeader as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    history = session_service.get_history(db, body.session_id)
    custom_prompt = body.system_prompt or session_service.get_system_prompt(db, body.session_id)
    system_prompt = custom_prompt or settings.default_system_prompt

    messages = (
        [{"role": "system", "content": system_prompt}]
        + session_service.history_as_llm_messages(history)
        + [{"role": "user", "content": body.message}]
    )

    try:
        result = await llm_service.resolve(messages, simulation)
    except llm_service.AllProvidersUnavailable as exc:
        log.error("all keys failed (first key error: %s)", exc.reason)
        # Nothing is persisted for a failed turn.
        raise HTTPException(status_code=503, detail="all providers unavailable")
    except llm_service.ProviderRejectedRequest as exc:
        log.error("request rejected by every key: %s", exc.reason)
        raise HTTPException(status_code=502, detail="request rejected by provider")

    metadata = ChatMetadata(
        resolution_source=result.resolution_source,
        model=result.model,
        latency_ms=int(round((time.perf_counter() - started) * 1000)),
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        key_id=result.key_id,
        fallback_attempts=result.fallback_attempts,
    )

    session_service.save_exchange(
        db,
        session_id=body.session_id,
        user_text=body.message,
        assistant_text=result.reply,
        metadata=metadata.model_dump(),
        system_prompt=body.system_prompt,
    )

    return ChatResponse(session_id=body.session_id, reply=result.reply, metadata=metadata)
