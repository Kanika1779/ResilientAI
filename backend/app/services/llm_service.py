"""Resolve a prompt to a reply through a LiteLLM Router + LiteLLM's built-in cache.

Router layout: one model group per key (key_1, key_2, ...), all serving the same
model, chained with ordered fallbacks key_1 -> key_2 -> ... Each key gets exactly
one attempt (num_retries=0). Cooldowns are disabled so a failure (real or
simulated) on one request never changes which key the NEXT request starts with.

  cache hit                -> LLM_CACHE, key_id=None, fallback_attempts=0
  served by key_n          -> LIVE_INFERENCE, key_id=key_n, fallback_attempts=n-1
  every key failed         -> AllProvidersUnavailable (503)
  request-level rejection  -> ProviderRejectedRequest (502)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import litellm
from litellm import Router

from ..config import Settings, settings
from . import failure_sim
from .cache_service import response_cache  # noqa: F401  (enables litellm.cache on import)
from .error_policy import EmptyCompletion, is_provider_error, should_failover

log = logging.getLogger("resilientai.llm")

litellm.suppress_debug_info = True
litellm.drop_params = True
failure_sim.install()


class AllProvidersUnavailable(Exception):
    def __init__(self, reason: str):
        super().__init__("all providers unavailable")
        self.reason = reason  # never contains secrets


class ProviderRejectedRequest(Exception):
    """Every key rejected the request itself (e.g. context too long, safety refusal)."""

    def __init__(self, reason: str):
        super().__init__("request rejected by provider")
        self.reason = reason


@dataclass(frozen=True)
class Resolution:
    reply: str
    model: str
    input_tokens: int
    output_tokens: int
    resolution_source: str  # LIVE_INFERENCE | LLM_CACHE
    key_id: str | None
    fallback_attempts: int


def build_router(cfg: Settings) -> Router | None:
    ids = [s.key_id for s in cfg.keys]
    if not ids:
        return None
    return Router(
        model_list=[
            {
                "model_name": s.key_id,
                "litellm_params": {
                    "model": cfg.model_name,
                    "api_key": s.api_key,
                    "timeout": cfg.request_timeout_s,
                },
                "model_info": {"id": s.key_id},
            }
            for s in cfg.keys
        ],
        # Each key falls back to every later key, in order.
        fallbacks=[{ids[i]: ids[i + 1:]} for i in range(len(ids) - 1)],
        max_fallbacks=len(ids),
        num_retries=0,
        disable_cooldowns=True,
        cache_responses=True,
        # Each key is its own model group, and LiteLLM keys the cache by model group
        # inside a Router. One caching group makes every key share one cache, so a
        # reply produced by key_2 is a hit for a request that starts at key_1.
        caching_groups=[tuple(ids)] if len(ids) > 1 else None,
    )


router = build_router(settings)
KEY_IDS = [s.key_id for s in settings.keys]


def _reason(exc: Exception) -> str:
    code = getattr(exc, "status_code", None)
    return f"{type(exc).__name__}({code})" if code else type(exc).__name__


def _valid_count(value) -> int | None:
    # bool is an int subclass; reject it along with negatives and non-integers.
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _count_tokens(**kwargs) -> int:
    """Local tokenizer estimate, only when the provider omits usage. Never raises."""
    try:
        return max(0, int(litellm.token_counter(model=settings.model_name, **kwargs)))
    except Exception:
        log.warning("token_counter failed; reporting 0 tokens")
        return 0


def _extract(resp, messages: list[dict]) -> tuple[str, int, int]:
    try:
        content = (resp.choices[0].message.content or "").strip()
    except (AttributeError, IndexError, TypeError):
        raise EmptyCompletion("provider response had no choices")
    if not content:
        raise EmptyCompletion("provider returned an empty completion")
    usage = getattr(resp, "usage", None)
    in_tok = _valid_count(getattr(usage, "prompt_tokens", None))
    out_tok = _valid_count(getattr(usage, "completion_tokens", None))
    if in_tok is None or out_tok is None:
        log.warning("provider usage missing/invalid; estimating with local tokenizer")
    if in_tok is None:
        in_tok = _count_tokens(messages=messages)
    if out_tok is None:
        out_tok = _count_tokens(text=content)
    return content, in_tok, out_tok


async def resolve(messages: list[dict], simulation: dict[str, str] | None = None) -> Resolution:
    if router is None:
        raise AllProvidersUnavailable("no API keys configured")

    model = settings.model_name
    start = 0                     # index of the key group the Router starts at
    read_cache = not simulation   # a failover demo must exercise the keys, not the cache

    while start < len(KEY_IDS):
        kwargs: dict = {"metadata": {failure_sim.METADATA_KEY: simulation or {}}}
        if not read_cache:
            kwargs["cache"] = {"no-cache": True}  # skip lookup, still store the result
        try:
            resp = await router.acompletion(model=KEY_IDS[start], messages=messages, **kwargs)
        except Exception as exc:
            if not is_provider_error(exc):
                raise  # a bug in our code -> global handler -> 500
            if should_failover(exc):
                raise AllProvidersUnavailable(_reason(exc)) from exc
            raise ProviderRejectedRequest(_reason(exc)) from exc

        hidden = getattr(resp, "_hidden_params", {}) or {}
        cache_hit = bool(hidden.get("cache_hit"))
        served = hidden.get("model_id")
        try:
            reply, in_tok, out_tok = _extract(resp, messages)
        except EmptyCompletion:
            # The Router treats an empty 200 as success, but the contract requires a
            # non-empty reply: continue the chain from the next key, bypassing the cache.
            log.warning("empty completion (cache_hit=%s, key=%s)", cache_hit, served)
            read_cache = False
            if not cache_hit:
                start = (KEY_IDS.index(served) + 1) if served in KEY_IDS else len(KEY_IDS)
            continue

        if cache_hit:
            return Resolution(reply, model, in_tok, out_tok, "LLM_CACHE", None, 0)

        if served not in KEY_IDS:  # defensive: never report an unknown key
            log.error("router did not report a known serving key: %r", served)
            raise AllProvidersUnavailable("unknown serving key")
        attempts = KEY_IDS.index(served)  # ordered chain: every earlier key failed
        log.info("key=%s ok after %d failed attempt(s)", served, attempts)
        return Resolution(reply, model, in_tok, out_tok, "LIVE_INFERENCE", served, attempts)

    raise AllProvidersUnavailable("all keys failed or returned empty completions")
