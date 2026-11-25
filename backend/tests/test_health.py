from app.config import settings


def test_health_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "keys_configured": 2, "cache_enabled": True}


def test_health_never_leaks_keys(client):
    body = client.get("/health").text
    for slot in settings.keys:
        assert slot.api_key not in body


def test_api_keys_are_redacted_from_all_logs(client, provider, caplog):
    """Even if a provider error echoes the key (Gemini sends it in the URL), logs mask it."""
    import logging

    import litellm

    from app.logging_setup import configure_logging

    configure_logging()
    leaky = litellm.AuthenticationError(
        "401 for url https://generativelanguage.googleapis.com/v1beta/models/x?key=secret-key-one",
        llm_provider="gemini", model="m",
    )
    provider.fail = {"key_1": leaky, "key_2": leaky}
    with caplog.at_level(logging.INFO):
        client.post("/chat", json={"session_id": "s-leak", "message": "hi"})
        logging.getLogger("LiteLLM Router").error("direct: %s", "secret-key-two")
    text = caplog.text
    assert "secret-key-one" not in text and "secret-key-two" not in text
    assert "***" in text
