"""Classify the error that ends a request after the Router exhausted its chain.

Note: when every key fails, the LiteLLM Router re-raises the FIRST key's error,
so that is the error classified here.

The LiteLLM Router itself fails over on every provider error. This policy only
decides how a TOTAL failure is reported:

  key-level / transient (429, quota, 401/403, timeouts, 5xx, ...) -> 503
      "all providers unavailable"   (the contract's case)
  request-level (context too long, safety refusal, unknown model,
      malformed request) -> 502 "request rejected by provider"
  not a provider error at all (a bug in our code) -> re-raised -> 500

Biased toward 503: any 400 mentioning keys/billing/quota/region is key-level.
"""
from __future__ import annotations

import litellm

# Request-level problems: identical on every key.
_FATAL_TYPES: tuple[type[Exception], ...] = (
    litellm.ContextWindowExceededError,     # prompt too long for the model
    litellm.ContentPolicyViolationError,    # provider safety refusal
    litellm.NotFoundError,                  # model name doesn't exist (config error)
    litellm.UnprocessableEntityError,       # malformed request
)
_FATAL_STATUS = {400, 404, 413, 422}

# 400s that are really about the key/project, not the request (e.g. Gemini
# FAILED_PRECONDITION for billing, or an unmapped invalid-key message).
_KEY_SPECIFIC_HINTS = (
    "api key", "api_key", "apikey", "billing", "quota", "project",
    "permission", "precondition", "location", "region", "credential",
)

class EmptyCompletion(Exception):
    """Provider returned 200 with no text. Treated as a key-level failure."""


def _status(exc: Exception) -> int | None:
    code = getattr(exc, "status_code", None)
    return code if isinstance(code, int) else None


def is_provider_error(exc: Exception) -> bool:
    """False for bugs in our own code (TypeError, KeyError, ...): those must
    surface as a 500, not be masked by failover or blamed on the provider."""
    return isinstance(exc, EmptyCompletion) or _is_litellm_exc(exc)


def should_failover(exc: Exception) -> bool:
    """Only meaningful for provider errors (see is_provider_error)."""
    if isinstance(exc, EmptyCompletion):
        return True
    message = str(exc).lower()
    if any(hint in message for hint in _KEY_SPECIFIC_HINTS):
        return True
    if isinstance(exc, _FATAL_TYPES):
        return False
    if isinstance(exc, litellm.BadRequestError) or _status(exc) in _FATAL_STATUS:
        return False
    # 401/403/408/429/5xx, timeouts, connection errors, unknown provider errors.
    return True


def _is_litellm_exc(exc: Exception) -> bool:
    return type(exc).__module__.split(".")[0] == "litellm"
