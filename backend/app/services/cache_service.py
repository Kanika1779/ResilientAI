"""LiteLLM's built-in response cache (in-memory), enabled globally.

Cache identity is LiteLLM's own key over the model + full message list
(system prompt + history + new message). The API key is excluded by LiteLLM,
and we never pass the session id (no `user=` / no session in cached params),
so the same first message in a new session is a hit.

The Router is created with cache_responses=True; LiteLLM looks the cache up
inside each call before contacting the provider, so a hit never uses a key.
"""
from __future__ import annotations

import logging

import litellm
from litellm.caching.caching import Cache

from ..config import settings

log = logging.getLogger("resilientai.cache")


class CacheState:
    def __init__(self) -> None:
        self.enabled = False

    def enable(self) -> None:
        litellm.cache = Cache(type="local", ttl=settings.cache_ttl_s)
        self.enabled = self._self_check()

    @staticmethod
    def _self_check() -> bool:
        """Import the module chain LiteLLM loads on a cache hit. This both
        verifies the undeclared deps are installed and pre-warms the imports,
        so the first real cache hit isn't slowed by ~150 ms of module loading."""
        try:
            import litellm.llms.anthropic.messages.native.response_cache  # noqa: F401
            from litellm.caching.caching_handler import LLMCachingHandler  # noqa: F401
            return True
        except Exception as exc:
            log.error("LiteLLM cache-hit path unavailable (%s); reporting cache disabled", exc)
            return False

    def clear(self) -> None:
        if litellm.cache is not None:
            litellm.cache.cache.flush_cache()


response_cache = CacheState()
response_cache.enable()
