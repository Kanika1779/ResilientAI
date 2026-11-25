import pytest

from app.config import settings


def test_valid_chat_returns_full_contract(client):
    r = client.post("/chat", json={"session_id": "s-1", "message": "What is AI?"})
    assert r.status_code == 200
    body = r.json()
    assert body["session_id"] == "s-1"
    assert body["reply"].startswith("answer to: What is AI?")
    meta = body["metadata"]
    assert set(meta) == {
        "resolution_source", "model", "latency_ms", "input_tokens",
        "output_tokens", "key_id", "fallback_attempts",
    }
    assert meta["resolution_source"] == "LIVE_INFERENCE"
    assert meta["model"] == "gemini/gemini-3.5-flash-lite"
    assert meta["key_id"] == "key_1"
    assert meta["fallback_attempts"] == 0
    assert isinstance(meta["latency_ms"], int) and meta["latency_ms"] >= 0
    assert meta["input_tokens"] > 0 and meta["output_tokens"] > 0


@pytest.mark.parametrize(
    "payload",
    [
        {"message": "hi"},                                  # missing session_id
        {"session_id": "s"},                                # missing message
        {"session_id": "s", "message": ""},                 # empty
        {"session_id": "s", "message": "   \n\t "},         # whitespace only
        {"session_id": "s", "message": "x" * 4001},         # too long
        {"session_id": "", "message": "hi"},                # empty session id
        {"session_id": "s" * 129, "message": "hi"},         # session id too long
        {"session_id": "s", "message": 123},                # wrong type
    ],
)
def test_invalid_requests_are_422_and_not_stored(client, provider, payload):
    r = client.post("/chat", json=payload)
    assert r.status_code == 422
    assert "detail" in r.json()
    assert provider.calls == []


def test_message_of_exactly_4000_chars_is_allowed(client):
    r = client.post("/chat", json={"session_id": "s", "message": "x" * 4000})
    assert r.status_code == 200


def test_message_is_trimmed(client, provider):
    client.post("/chat", json={"session_id": "s", "message": "  hello  "})
    assert provider.calls[0]["messages"][-1]["content"] == "hello"


def test_reply_never_contains_secrets(client):
    text = client.post("/chat", json={"session_id": "s", "message": "hi"}).text
    for slot in settings.keys:
        assert slot.api_key not in text


def test_custom_system_prompt_is_used_and_remembered(client, provider):
    client.post("/chat", json={"session_id": "s", "message": "a", "system_prompt": "Be a pirate."})
    client.post("/chat", json={"session_id": "s", "message": "b"})
    assert provider.calls[0]["messages"][0] == {"role": "system", "content": "Be a pirate."}
    assert provider.calls[1]["messages"][0] == {"role": "system", "content": "Be a pirate."}


def test_unexpected_error_returns_safe_json(client, provider, monkeypatch):
    from app.services import session_service

    def explode(*a, **k):
        raise RuntimeError("secret internals")

    monkeypatch.setattr(session_service, "save_exchange", explode)
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.post("/chat", json={"session_id": "s", "message": "hi"})
    assert r.status_code == 500
    assert r.json() == {"detail": "internal server error"}
    assert "secret internals" not in r.text


def test_malformed_json_is_422(client, provider):
    r = client.post("/chat", content=b'{"session_id": "s", "message": ', headers={"Content-Type": "application/json"})
    assert r.status_code == 422
    assert "detail" in r.json()
    assert provider.calls == []
