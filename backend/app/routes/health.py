from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..config import settings
from ..database import db_is_reachable
from ..services.cache_service import response_cache

router = APIRouter()


@router.get("/health")
def health():
    keys = settings.keys_configured
    healthy = db_is_reachable() and keys >= 2 and response_cache.enabled
    body = {
        "status": "ok" if healthy else "degraded",
        "keys_configured": keys,
        "cache_enabled": response_cache.enabled,
    }
    # Never report healthy when the DB is down or the key pool can't fail over.
    return JSONResponse(body, status_code=200 if healthy else 503)
