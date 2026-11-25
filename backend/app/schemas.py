"""Request/response contracts. Field names match the assignment exactly."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ChatRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=128)
    message: str = Field(..., min_length=1, max_length=4000)
    system_prompt: str | None = Field(default=None, max_length=4000)

    @field_validator("session_id", "message", mode="before")
    @classmethod
    def _strip(cls, v):
        # Trim first, then the length constraints above apply to the trimmed value.
        return v.strip() if isinstance(v, str) else v

    @field_validator("system_prompt", mode="before")
    @classmethod
    def _strip_prompt(cls, v):
        if isinstance(v, str):
            v = v.strip()
            return v or None
        return v


ResolutionSource = Literal["LIVE_INFERENCE", "LLM_CACHE"]


class ChatMetadata(BaseModel):
    resolution_source: ResolutionSource
    model: str
    latency_ms: int
    input_tokens: int
    output_tokens: int
    key_id: str | None
    fallback_attempts: int


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    metadata: ChatMetadata


class HistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    created_at: str
    metadata: dict | None = None


class HistoryResponse(BaseModel):
    session_id: str
    messages: list[HistoryMessage]


class HealthResponse(BaseModel):
    status: str
    keys_configured: int
    cache_enabled: bool
