"""X-Simulate-Failure test hook.

Format:  key_1=429            -> key_1 fails with 429
         key_1=429,key_2=500  -> both fail
         *=503                -> every key fails
         key_1=quota          -> quota-exhausted style 429 on key_1

The plan travels in the request's LiteLLM metadata. A LiteLLM callback runs
just before each Router deployment (= each key) is called and raises the
matching LiteLLM exception, so the Router's real fallback logic handles it
exactly like a provider error. Real provider quota is never touched.
Ignored unless ENABLE_FAILURE_SIMULATION=true.
"""
from __future__ import annotations

import re

import httpx
import litellm
from litellm.integrations.custom_logger import CustomLogger

HEADER_NAME = "X-Simulate-Failure"
METADATA_KEY = "resilientai_simulate"
_TARGET = re.compile(r"^(\*|key_\d+)$")
_CODE = re.compile(r"^(quota|[45]\d\d)$")


class InvalidSimulationHeader(ValueError):
    pass


def parse(header_value: str | None) -> dict[str, str] | None:
    """Return {target: code} or None when the header is absent/empty."""
    if header_value is None or not header_value.strip():
        return None
    plan: dict[str, str] = {}
    for part in header_value.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise InvalidSimulationHeader(f"invalid {HEADER_NAME} entry: {part!r}")
        target, code = (s.strip().lower() for s in part.split("=", 1))
        if not _TARGET.match(target) or not _CODE.match(code):
            raise InvalidSimulationHeader(f"invalid {HEADER_NAME} entry: {part!r}")
        plan[target] = code
    return plan or None


def failure_for(plan: dict[str, str] | None, key_id: str | None) -> str | None:
    """The simulated failure code for this key, if any. Explicit key beats '*'."""
    if not plan or not key_id:
        return None
    return plan.get(key_id) or plan.get("*")


def simulated_exception(code: str, key_id: str) -> Exception:
    """The LiteLLM exception a real provider failure with this status maps to."""
    msg = f"simulated failure on {key_id} ({code})"
    kw = {"llm_provider": "simulation", "model": "simulation"}
    if code in ("429", "quota"):
        return litellm.RateLimitError(msg + (": quota exceeded" if code == "quota" else ""), **kw)
    if code == "502":
        return litellm.BadGatewayError(msg, **kw)
    if code == "503":
        return litellm.ServiceUnavailableError(msg, **kw)
    if code == "401":
        return litellm.AuthenticationError(msg, **kw)
    if code == "403":
        resp = httpx.Response(403, request=httpx.Request("POST", "http://simulation"))
        return litellm.PermissionDeniedError(msg, response=resp, **kw)
    if code.startswith("5"):
        return litellm.InternalServerError(msg, **kw)
    return litellm.BadRequestError(msg, **kw)


class SimulationHook(CustomLogger):
    """Runs after the Router picks a key, before the request goes out."""

    async def async_pre_call_deployment_hook(self, kwargs, call_type):
        plan = (kwargs.get("metadata") or {}).get(METADATA_KEY)
        if plan:
            key_id = (kwargs.get("model_info") or {}).get("id")
            code = failure_for(plan, key_id)
            if code:
                raise simulated_exception(code, key_id)
        return kwargs


_hook = SimulationHook()


def install() -> None:
    if _hook not in litellm.callbacks:
        litellm.callbacks.append(_hook)
