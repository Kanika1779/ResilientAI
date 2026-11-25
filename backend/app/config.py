"""Application configuration, read once from environment variables.

No secrets are hardcoded. API keys are only ever referred to outside this
module by their identifiers (key_1, key_2, ...).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class KeySlot:
    """One configured API key. `key_id` is safe to expose; `api_key` is not."""

    key_id: str
    api_key: str = field(repr=False)


@dataclass(frozen=True)
class Settings:
    keys: tuple[KeySlot, ...]
    model_name: str
    database_url: str
    allowed_origins: tuple[str, ...]
    allowed_origin_regex: str | None
    enable_failure_simulation: bool
    default_system_prompt: str
    request_timeout_s: float
    cache_ttl_s: int

    @property
    def keys_configured(self) -> int:
        return len(self.keys)


def load_settings() -> Settings:
    raw_keys = _split_csv(os.getenv("LLM_API_KEYS"))
    keys = tuple(KeySlot(key_id=f"key_{i}", api_key=k) for i, k in enumerate(raw_keys, start=1))
    return Settings(
        keys=keys,
        model_name=os.getenv("MODEL_NAME", "gemini/gemini-3.5-flash-lite"),
        database_url=os.getenv("DATABASE_URL", "sqlite:///./app.db"),
        allowed_origins=tuple(_split_csv(os.getenv("ALLOWED_ORIGINS", "http://localhost:3000"))),
        allowed_origin_regex=os.getenv("ALLOWED_ORIGIN_REGEX") or None,
        enable_failure_simulation=_as_bool(os.getenv("ENABLE_FAILURE_SIMULATION"), False),
        default_system_prompt=os.getenv(
            "DEFAULT_SYSTEM_PROMPT", "You are a helpful, concise AI assistant."
        ),
        request_timeout_s=float(os.getenv("LLM_TIMEOUT_SECONDS", "30")),
        cache_ttl_s=int(os.getenv("CACHE_TTL_SECONDS", "86400")),
    )


settings = load_settings()
