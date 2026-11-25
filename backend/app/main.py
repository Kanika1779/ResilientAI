"""ResilientAI FastAPI entrypoint.

Application endpoints (exactly three):
  GET  /health
  POST /chat
  GET  /sessions/{session_id}/messages
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import settings
from .logging_setup import configure_logging

configure_logging()  # before importing LiteLLM-using modules, so their loggers are covered

from .database import init_db  # noqa: E402
from .routes import chat, health, sessions  # noqa: E402

log = logging.getLogger("resilientai")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    configure_logging()  # again: LiteLLM may add its own handlers on import
    init_db()
    log.info(
        "started: model=%s keys=%d failure_simulation=%s",
        settings.model_name,
        settings.keys_configured,
        settings.enable_failure_simulation,
    )
    if settings.keys_configured < 2:
        log.warning("fewer than 2 API keys configured; failover is impossible")
    yield


app = FastAPI(title="ResilientAI", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.allowed_origins),
    allow_origin_regex=settings.allowed_origin_regex,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-Simulate-Failure"],
)


@app.exception_handler(Exception)
async def unhandled(_request: Request, exc: Exception):
    # Safe JSON instead of a stack trace / HTML page.
    log.exception("unhandled error: %s", type(exc).__name__)
    return JSONResponse(status_code=500, content={"detail": "internal server error"})


app.include_router(health.router)
app.include_router(chat.router)
app.include_router(sessions.router)
