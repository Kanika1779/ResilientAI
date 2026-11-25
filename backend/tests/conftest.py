"""Test harness: temp SQLite DB, two fake keys, and a fake provider.

The fake replaces ONLY LiteLLM's innermost step (litellm.main.mock_completion,
reached via `mock_response`). Everything above it is real: our routes, the
LiteLLM Router and its fallback chain, the simulation hook, LiteLLM's built-in
cache lookup/store, and SQLite. So `provider.calls` lists only requests that
actually reached a "provider" (not cache hits, not simulated failures).
"""
import os
import sys
import tempfile
import time
from pathlib import Path

_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["LLM_API_KEYS"] = "secret-key-one,secret-key-two"
os.environ["ENABLE_FAILURE_SIMULATION"] = "true"
os.environ["MODEL_NAME"] = "gemini/gemini-3.5-flash-lite"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import litellm  # noqa: E402
import litellm.main  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services.cache_service import response_cache  # noqa: E402

KEY_IDS = {"secret-key-one": "key_1", "secret-key-two": "key_2"}
_SENTINEL = "__fake_provider__:"


class FakeProvider:
    """Answers like a model; can be told to fail or return empty text per key."""

    def __init__(self):
        self.calls: list[dict] = []
        self.fail: dict[str, Exception] = {}
        self.empty: set[str] = set()
        self.delay_s = 0.0

    def __call__(self, model, messages, mock_response=None, **kwargs):
        key_id = KEY_IDS[mock_response[len(_SENTINEL):]]
        if self.delay_s:
            time.sleep(self.delay_s)  # mimic real provider latency
        self.calls.append({"key_id": key_id, "messages": messages})
        if key_id in self.fail:
            raise self.fail[key_id]
        last = messages[-1]["content"]
        reply = "" if key_id in self.empty else (
            f"answer to: {last} (turns={sum(m['role'] == 'user' for m in messages)})"
        )
        prompt_tokens = sum(len(m["content"].split()) for m in messages) + 3 * len(messages)
        return litellm.ModelResponse(
            model=model,
            choices=[{"message": {"role": "assistant", "content": reply}, "finish_reason": "stop"}],
            usage=litellm.Usage(
                prompt_tokens=prompt_tokens,
                completion_tokens=len(reply.split()),
                total_tokens=prompt_tokens + len(reply.split()),
            ),
        )


def rate_limit():
    return litellm.RateLimitError("rate limited", llm_provider="gemini", model="m")


def server_error():
    return litellm.InternalServerError("boom", llm_provider="gemini", model="m")


@pytest.fixture()
def provider(monkeypatch):
    fake = FakeProvider()
    real_acompletion = litellm.acompletion

    async def route_to_fake(*args, **kwargs):
        # Tag the call with its key so the fake knows which "provider account" it is.
        kwargs["mock_response"] = _SENTINEL + kwargs["api_key"]
        return await real_acompletion(*args, **kwargs)

    monkeypatch.setattr(litellm, "acompletion", route_to_fake)
    monkeypatch.setattr(litellm.main, "mock_completion", fake)
    return fake


@pytest.fixture()
def client(provider):
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    response_cache.clear()
    with TestClient(app) as c:
        yield c
