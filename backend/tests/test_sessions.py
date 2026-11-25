def chat(client, session, msg):
    return client.post("/chat", json={"session_id": session, "message": msg}).json()


def test_unknown_session_is_404(client):
    r = client.get("/sessions/nope/messages")
    assert r.status_code == 404
    assert r.json() == {"detail": "session not found"}


def test_history_oldest_first_without_system_prompt(client):
    chat(client, "s", "What is Python?")
    chat(client, "s", "What are its advantages?")
    body = client.get("/sessions/s/messages").json()
    assert body["session_id"] == "s"
    roles = [m["role"] for m in body["messages"]]
    assert roles == ["user", "assistant", "user", "assistant"]
    assert body["messages"][0]["content"] == "What is Python?"
    assert body["messages"][2]["content"] == "What are its advantages?"
    assert all(m["role"] != "system" for m in body["messages"])
    assert body["messages"][0]["metadata"] is None
    assert body["messages"][1]["metadata"]["resolution_source"] == "LIVE_INFERENCE"


def test_multi_turn_sends_full_history(client, provider):
    chat(client, "s", "What is Python?")
    chat(client, "s", "What are its advantages?")
    sent = provider.calls[1]["messages"]
    assert [m["role"] for m in sent] == ["system", "user", "assistant", "user"]
    assert sent[1]["content"] == "What is Python?"
    assert sent[3]["content"] == "What are its advantages?"


def test_sessions_are_isolated(client, provider):
    chat(client, "s-1", "secret one")
    chat(client, "s-2", "hello two")
    sent = provider.calls[1]["messages"]
    assert all("secret one" not in m["content"] for m in sent)
    assert len(client.get("/sessions/s-2/messages").json()["messages"]) == 2


def test_tokens_are_per_request_not_cumulative(client):
    first = chat(client, "s", "What is Python?")["metadata"]
    second = chat(client, "s", "Why?")["metadata"]
    # input grows with history; output reflects only that reply
    assert second["input_tokens"] > first["input_tokens"]
    assert second["output_tokens"] < first["input_tokens"] + second["input_tokens"]


def test_identical_first_prompts_report_same_input_tokens(client):
    a = chat(client, "s-a", "Explain AI")["metadata"]["input_tokens"]
    b = chat(client, "s-b", "Explain AI")["metadata"]["input_tokens"]
    assert a == b


def test_history_survives_new_engine(client):
    """Simulates a container restart: a fresh engine on the same file sees the data."""
    chat(client, "s-persist", "remember me")
    from app.config import settings
    from app.database import make_engine
    from sqlalchemy import text

    fresh = make_engine(settings.database_url)
    with fresh.connect() as conn:
        n = conn.execute(text("SELECT COUNT(*) FROM messages WHERE session_id='s-persist'")).scalar()
    assert n == 2
