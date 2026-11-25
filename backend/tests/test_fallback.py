import litellm
import pytest

from conftest import rate_limit, server_error


def chat(client, msg="hello", session="s-f", header=None):
    headers = {"X-Simulate-Failure": header} if header else {}
    return client.post("/chat", json={"session_id": session, "message": msg}, headers=headers)


# ---- simulated failures (the hook evaluators will use) ----

@pytest.mark.parametrize("header", ["key_1=429", "key_1=500", "key_1=502", "key_1=503", "key_1=quota"])
def test_simulated_key1_failure_falls_back_to_key2(client, provider, header):
    r = chat(client, header=header)
    assert r.status_code == 200
    meta = r.json()["metadata"]
    assert meta["key_id"] == "key_2"
    assert meta["fallback_attempts"] == 1
    assert meta["resolution_source"] == "LIVE_INFERENCE"
    # a real (non-simulated) answer came back from key_2; key_1 was never called
    assert [c["key_id"] for c in provider.calls] == ["key_2"]
    assert r.json()["reply"].startswith("answer to:")


@pytest.mark.parametrize("header", ["key_1=429,key_2=500", "*=429", "*=503"])
def test_all_keys_failing_returns_503_and_stores_nothing(client, provider, header):
    r = chat(client, session="s-dead", header=header)
    assert r.status_code == 503
    assert r.json() == {"detail": "all providers unavailable"}
    assert client.get("/sessions/s-dead/messages").status_code == 404


def test_explicit_key_overrides_wildcard(client):
    # '*' fails everyone except key_2, which is explicitly told to... also fail
    assert chat(client, header="*=429,key_2=500").status_code == 503


def test_malformed_simulation_header_is_422(client, provider):
    r = chat(client, header="key_1=banana")
    assert r.status_code == 422
    assert provider.calls == []


def test_simulation_ignored_when_disabled(client, monkeypatch):
    from app.routes import chat as chat_route
    from dataclasses import replace

    monkeypatch.setattr(chat_route, "settings", replace(chat_route.settings, enable_failure_simulation=False))
    r = chat(client, header="*=429")
    assert r.status_code == 200
    assert r.json()["metadata"]["key_id"] == "key_1"


def test_simulated_failure_does_not_poison_next_request(client):
    """No Router-style cooldown: a clean request after a failover uses key_1 again."""
    chat(client, msg="first", header="key_1=429")
    r = chat(client, msg="second")
    assert r.json()["metadata"]["key_id"] == "key_1"
    assert r.json()["metadata"]["fallback_attempts"] == 0


# ---- real provider exceptions (what LiteLLM raises in production) ----

@pytest.mark.parametrize(
    "exc",
    [
        rate_limit(),
        server_error(),
        litellm.ServiceUnavailableError("down", llm_provider="gemini", model="m"),
        litellm.AuthenticationError("bad key", llm_provider="gemini", model="m"),
        litellm.Timeout("slow", model="m", llm_provider="gemini"),
    ],
    ids=["429", "500", "503", "401", "timeout"],
)
def test_real_provider_error_on_key1_falls_back(client, provider, exc):
    provider.fail["key_1"] = exc
    r = chat(client)
    assert r.status_code == 200
    assert r.json()["metadata"]["key_id"] == "key_2"
    assert r.json()["metadata"]["fallback_attempts"] == 1
    assert [c["key_id"] for c in provider.calls] == ["key_1", "key_2"]


def test_each_key_tried_exactly_once_when_all_fail(client, provider):
    provider.fail = {"key_1": rate_limit(), "key_2": server_error()}
    r = chat(client)
    assert r.status_code == 503
    assert [c["key_id"] for c in provider.calls] == ["key_1", "key_2"]
