"""Error classification of TOTAL failures (503 vs 502 vs 500) and Router edge cases."""
from types import SimpleNamespace

import httpx
import litellm
import pytest

from app.services import llm_service
from app.services.error_policy import EmptyCompletion, is_provider_error, should_failover


def _resp(status):
    return httpx.Response(status, request=httpx.Request("POST", "http://provider"))


FAILOVER = {
    "429": litellm.RateLimitError("rate limited", llm_provider="gemini", model="m"),
    "quota": litellm.RateLimitError("RESOURCE_EXHAUSTED quota", llm_provider="gemini", model="m"),
    "401": litellm.AuthenticationError("API key not valid", llm_provider="gemini", model="m"),
    "403": litellm.PermissionDeniedError("denied", llm_provider="gemini", model="m", response=_resp(403)),
    "500": litellm.InternalServerError("boom", llm_provider="gemini", model="m"),
    "502": litellm.BadGatewayError("bad gateway", llm_provider="gemini", model="m"),
    "503": litellm.ServiceUnavailableError("down", llm_provider="gemini", model="m"),
    "timeout": litellm.Timeout("slow", model="m", llm_provider="gemini"),
    "connection": litellm.APIConnectionError("reset", llm_provider="gemini", model="m"),
    "empty": EmptyCompletion("empty"),
    # 400s that are really about the key / project:
    "400-invalid-key": litellm.BadRequestError("API key not valid. Please pass a valid API key.", model="m", llm_provider="gemini"),
    "400-billing": litellm.BadRequestError("FAILED_PRECONDITION: billing not enabled for project", model="m", llm_provider="gemini"),
}

FATAL = {
    "400": litellm.BadRequestError("Invalid JSON payload", model="m", llm_provider="gemini"),
    "context": litellm.ContextWindowExceededError("input too long", model="m", llm_provider="gemini"),
    "policy": litellm.ContentPolicyViolationError("blocked by safety", model="m", llm_provider="gemini"),
    "404": litellm.NotFoundError("model not found", model="m", llm_provider="gemini"),
}


@pytest.mark.parametrize("name", FAILOVER)
def test_failover_errors(name):
    assert is_provider_error(FAILOVER[name])
    assert should_failover(FAILOVER[name]) is True


@pytest.mark.parametrize("name", FATAL)
def test_fatal_errors(name):
    assert is_provider_error(FATAL[name])
    assert should_failover(FATAL[name]) is False


def test_code_bugs_are_not_provider_errors():
    assert not is_provider_error(TypeError("oops"))
    assert not is_provider_error(KeyError("x"))


# ---- end-to-end through /chat (LiteLLM Router semantics) ----

def chat(client, header=None, session="s-ep", msg="hi"):
    headers = {"X-Simulate-Failure": header} if header else {}
    return client.post("/chat", json={"session_id": session, "message": msg}, headers=headers)


@pytest.mark.parametrize("name", FATAL)
def test_request_level_error_on_every_key_is_502_and_stores_nothing(client, provider, name):
    provider.fail = {"key_1": FATAL[name], "key_2": FATAL[name]}
    r = chat(client)
    assert r.status_code == 502
    assert r.json() == {"detail": "request rejected by provider"}
    assert client.get("/sessions/s-ep/messages").status_code == 404


@pytest.mark.parametrize("name", FATAL)
def test_router_still_fails_over_on_request_level_error_from_one_key(client, provider, name):
    """The Router falls back on every error; if key_2 accepts, the user gets an answer."""
    provider.fail["key_1"] = FATAL[name]
    r = chat(client)
    assert r.status_code == 200
    assert r.json()["metadata"]["key_id"] == "key_2"


def test_total_failure_is_classified_by_first_keys_error(client, provider):
    """When the whole chain fails, the LiteLLM Router re-raises the FIRST key's error."""
    rl = litellm.RateLimitError("rl", llm_provider="gemini", model="m")
    provider.fail = {"key_1": rl, "key_2": FATAL["400"]}
    assert chat(client, session="x1").status_code == 503      # key-level first -> 503
    provider.fail = {"key_1": FATAL["400"], "key_2": rl}
    assert chat(client, session="x2").status_code == 502      # request-level first -> 502


def test_code_bug_surfaces_as_500_not_failover(provider, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app

    def buggy(resp, messages):
        raise TypeError("bug in our code")

    monkeypatch.setattr(llm_service, "_extract", buggy)
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.post("/chat", json={"session_id": "s-bug", "message": "hi"})
    assert r.status_code == 500
    assert r.json() == {"detail": "internal server error"}


def test_empty_completion_continues_chain_to_next_key(client, provider):
    provider.empty = {"key_1"}
    r = chat(client)
    assert r.status_code == 200
    assert r.json()["reply"]
    assert r.json()["metadata"]["key_id"] == "key_2"
    assert r.json()["metadata"]["fallback_attempts"] == 1


def test_empty_completion_is_never_served_from_cache(client, provider):
    provider.empty = {"key_1"}
    chat(client, session="a", msg="Explain AI")   # key_1 empty (cached by LiteLLM), key_2 answers
    provider.empty = set()
    r = chat(client, session="b", msg="Explain AI").json()
    assert r["reply"]                              # never an empty reply
    assert r["reply"].startswith("answer to:")


def test_empty_on_every_key_is_503(client, provider):
    provider.empty = {"key_1", "key_2"}
    r = chat(client)
    assert r.status_code == 503
    assert r.json() == {"detail": "all providers unavailable"}


# ---- tokenizer fallback safeguards ----

def _reply(usage):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="four word reply here"))], usage=usage)


MSGS = [{"role": "system", "content": "sys"}, {"role": "user", "content": "hello there"}]


def test_provider_usage_is_preferred():
    _, i, o = llm_service._extract(_reply(SimpleNamespace(prompt_tokens=11, completion_tokens=4)), MSGS)
    assert (i, o) == (11, 4)


@pytest.mark.parametrize(
    "usage",
    [None, SimpleNamespace(prompt_tokens=None, completion_tokens=None),
     SimpleNamespace(prompt_tokens=-5, completion_tokens="7"), SimpleNamespace(prompt_tokens=True, completion_tokens=3.5)],
    ids=["no-usage", "nulls", "negative-and-string", "bool-and-float"],
)
def test_missing_or_invalid_usage_is_estimated(usage):
    _, i, o = llm_service._extract(_reply(usage), MSGS)
    assert isinstance(i, int) and i > 0
    assert isinstance(o, int) and o > 0


def test_partial_usage_keeps_the_valid_half():
    _, i, o = llm_service._extract(_reply(SimpleNamespace(prompt_tokens=11, completion_tokens=None)), MSGS)
    assert i == 11 and o > 0


def test_tokenizer_failure_never_breaks_reply(monkeypatch):
    def broken(**kwargs):
        raise RuntimeError("tokenizer exploded")

    monkeypatch.setattr(litellm, "token_counter", broken)
    reply, i, o = llm_service._extract(_reply(None), MSGS)
    assert reply == "four word reply here"
    assert (i, o) == (0, 0)
