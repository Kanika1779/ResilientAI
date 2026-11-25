from conftest import rate_limit


def chat(client, session, msg, header=None, **extra):
    headers = {"X-Simulate-Failure": header} if header else {}
    return client.post("/chat", json={"session_id": session, "message": msg, **extra}, headers=headers)


def test_same_first_message_in_new_session_is_cache_hit(client, provider):
    live = chat(client, "s-a", "Explain AI").json()
    cached = chat(client, "s-b", "Explain AI").json()

    assert live["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert cached["metadata"]["resolution_source"] == "LLM_CACHE"
    assert cached["reply"] == live["reply"]
    assert cached["metadata"]["key_id"] is None
    assert cached["metadata"]["fallback_attempts"] == 0
    # original usage is preserved, not recounted / zeroed
    assert cached["metadata"]["input_tokens"] == live["metadata"]["input_tokens"]
    assert cached["metadata"]["output_tokens"] == live["metadata"]["output_tokens"]
    assert cached["metadata"]["model"] == live["metadata"]["model"]
    assert len(provider.calls) == 1  # second request never reached a provider


def test_cache_hit_saved_to_its_own_session(client):
    chat(client, "s-a", "Explain AI")
    chat(client, "s-b", "Explain AI")
    msgs = client.get("/sessions/s-b/messages").json()["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[1]["metadata"]["resolution_source"] == "LLM_CACHE"


def test_different_message_is_live(client):
    chat(client, "s-a", "Explain AI")
    r = chat(client, "s-c", "Explain ML").json()
    assert r["metadata"]["resolution_source"] == "LIVE_INFERENCE"


def test_cache_identity_includes_history(client):
    """Same text, different conversation context -> must NOT be a cache hit."""
    chat(client, "s-a", "Tell me more")              # first turn of s-a
    chat(client, "s-b", "What is Python?")
    r = chat(client, "s-b", "Tell me more").json()   # same text, but with history
    assert r["metadata"]["resolution_source"] == "LIVE_INFERENCE"


def test_cache_identity_includes_system_prompt(client):
    chat(client, "s-a", "Hi", system_prompt="Be formal.")
    r = chat(client, "s-b", "Hi", system_prompt="Be a pirate.").json()
    assert r["metadata"]["resolution_source"] == "LIVE_INFERENCE"


def test_cache_hit_works_even_when_all_keys_are_down(client, provider):
    chat(client, "s-a", "Explain AI")
    provider.fail = {"key_1": rate_limit(), "key_2": rate_limit()}
    r = chat(client, "s-b", "Explain AI")
    assert r.status_code == 200
    assert r.json()["metadata"]["resolution_source"] == "LLM_CACHE"


def test_simulation_bypasses_cache_lookup(client):
    """A failover demo must hit the key loop even for a previously cached prompt."""
    chat(client, "s-a", "Explain AI")
    r = chat(client, "s-b", "Explain AI", header="key_1=429").json()
    assert r["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert r["metadata"]["key_id"] == "key_2"


def test_failover_answer_is_cached_for_later(client):
    chat(client, "s-a", "Explain AI", header="key_1=429")
    r = chat(client, "s-b", "Explain AI").json()
    assert r["metadata"]["resolution_source"] == "LLM_CACHE"


def test_failed_request_is_not_cached(client, provider):
    chat(client, "s-a", "Explain AI", header="*=429")
    r = chat(client, "s-b", "Explain AI").json()
    assert r["metadata"]["resolution_source"] == "LIVE_INFERENCE"


def test_reply_from_key2_after_real_failure_is_shared_cache(client, provider):
    """Regression: each key is its own Router model group; without a shared caching
    group a reply produced by key_2 would never be a hit for requests starting at key_1."""
    provider.fail["key_1"] = rate_limit()
    first = chat(client, "s-a", "Explain AI").json()
    assert first["metadata"]["key_id"] == "key_2"
    provider.fail = {}
    second = chat(client, "s-b", "Explain AI").json()
    assert second["metadata"]["resolution_source"] == "LLM_CACHE"
    assert second["reply"] == first["reply"]


def test_cache_hit_is_faster_than_live(client, provider):
    provider.delay_s = 0.15  # a live call costs real provider time; a hit doesn't
    live = chat(client, "s-a", "Explain latency").json()["metadata"]
    hit = chat(client, "s-b", "Explain latency").json()["metadata"]
    assert live["resolution_source"] == "LIVE_INFERENCE"
    assert hit["resolution_source"] == "LLM_CACHE"
    assert hit["latency_ms"] < live["latency_ms"]
