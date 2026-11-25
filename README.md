# ResilientAI

A fault-tolerant AI chat app: React frontend, FastAPI backend, SQLite conversation storage, and LiteLLM for model calls. It has a multi-key failover loop, a response cache, and per-request token and latency metadata.

```
React (Vite, nginx) ──HTTP/JSON──▶ FastAPI ──▶ SQLite (/data/app.db, Docker volume)
                                     │
                                     └─▶ LiteLLM Router ─▶ key_1 ──fail──▶ key_2 ──fail──▶ 503
                                            (LiteLLM built-in cache checked before each provider call)
```

## 1. Live URLs

| | URL |
|---|---|
| Frontend | `TODO: https://<your-app>.vercel.app` |
| Backend | `TODO: https://<your-backend>.onrender.com` |
| Health | `TODO: https://<your-backend>.onrender.com/health` |

## 2. Run locally: with Docker and without

### Prerequisites
- Docker Desktop (with Compose v2)
- `make`. On Windows, use Git Bash, WSL, or `choco install make`. Without make, run the `docker compose` commands shown below.
- Two LLM API keys. For Gemini, create them in **two different Google Cloud projects**. Keys in one project share one quota, so a real 429 would hit both.

### With Docker
```bash
cp .env.example .env          # then put your two keys in LLM_API_KEYS
make up                       # = docker compose up -d --build
# Frontend: http://localhost:3000   Backend: http://localhost:8000/health
make down                     # = docker compose down (data is kept in the app_data volume)
```

### Without Docker
> **Windows note:** litellm 1.110.x ships a compiled native extension. Windows Smart App Control or a company app-control policy may block it (`DLL load failed ... An Application Control policy has blocked this file`). If you see this error, run the backend in **WSL** (Ubuntu), or use Docker: `make test` runs the test suite in a Linux container. Don't disable Smart App Control for this, because it can't be re-enabled without a Windows reset.

Backend (Python 3.12+):
```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
# set the variables from .env.example in your shell, with DATABASE_URL=sqlite:///./app.db
uvicorn app.main:app --port 8000
python -m pytest -q           # 91 tests, fake provider, no quota used (or: make test)
```
Frontend (Node 20+):
```bash
cd frontend
npm install
npm run dev                   # http://localhost:3000, calls VITE_API_URL (default http://localhost:8000)
```

## 3. Design decisions: key fallback, caching, SQLite session storage

### Request path (`POST /chat`)
1. Pydantic validates the body. `session_id` must be 1–128 characters. `message` must be 1–4000 characters after trimming. A bad body returns 422 and nothing is stored.
2. The session's history is loaded from SQLite (oldest first). The prompt is built as `[system] + history + [new user message]`. The frontend sends only the new message, never the whole history.
3. The LiteLLM Router resolves the prompt: built-in cache first, then the ordered key chain (described below).
4. Only after a successful reply are the user row and the assistant row written, in **one transaction**. A failed turn leaves no partial history.

### Key fallback: LiteLLM Router
- `LLM_API_KEYS=k1,k2,...` becomes the identifiers `key_1`, `key_2`, .... Only these identifiers ever leave the process. Raw keys never appear in responses, and a log filter (`app/logging_setup.py`) masks them in every log line, LiteLLM's included. That matters because Gemini sends the key in the request URL.
- **One `litellm.Router`, one model group per key**, all serving `MODEL_NAME`, chained with ordered fallbacks `key_1 → key_2 → …` (`services/llm_service.py`).
  - `num_retries=0`: each key gets exactly one attempt. The fallback chain *is* the retry policy.
  - `disable_cooldowns=True`: by default the Router puts a failed key on cooldown, so the *next* healthy request would silently skip key_1 and report misleading metadata. With cooldowns off, one request's failure never changes where the next request starts. `test_simulated_failure_does_not_poison_next_request` checks this.
- `key_id` is the deployment that answered, as the Router reports it. `fallback_attempts` is that key's position in the chain, because every earlier key must have failed.
- **Empty replies:** the Router counts an empty 200 as a success, but the contract requires a non-empty reply. So the app continues the chain from the next key itself, with the cache bypassed.
- **Total failure** (`services/error_policy.py`): the Router falls back on *every* provider error. When the whole chain fails, it re-raises the **first** key's error, which is then classified:
  - key-level or transient (429, quota, 401/403, timeouts, connection errors, 5xx, and any 400 that mentions the key, billing, quota or region) → `503 {"detail": "all providers unavailable"}`
  - request-level (context window exceeded, content-policy refusal, unknown model, malformed request) → `502 {"detail": "request rejected by provider"}`
  - a bug in our own code → `500 {"detail": "internal server error"}`, never hidden by failover
  
  Nothing is stored for any failed turn.

### Failure simulation
With `ENABLE_FAILURE_SIMULATION=true`, the plan in `X-Simulate-Failure` goes into the request's LiteLLM metadata. A LiteLLM callback (`async_pre_call_deployment_hook`, in `services/failure_sim.py`) runs after the Router picks a key and before the request goes out. If that key is listed, the callback raises the exact LiteLLM exception a real provider failure would produce (429 → `RateLimitError`, 500 → `InternalServerError`, 502 → `BadGatewayError`, 503 → `ServiceUnavailableError`). The Router's **real** fallback logic handles it like any provider error. Supported forms are `key_1=429`, `key_1=429,key_2=500`, `*=429` and `key_1=quota`. An explicit key entry takes priority over `*`. A malformed header returns 422. When the flag is off, the header is ignored.

While a simulation header is present, the cache *lookup* is skipped (`cache={"no-cache": True}`). This makes every failover demo exercise the keys, even for a prompt that is already cached. The successful reply is still stored in the cache.

### Caching: LiteLLM's built-in cache
- `litellm.cache = Cache(type="local")` (in memory) and `Router(cache_responses=True)`. LiteLLM looks up the cache inside each call, before contacting a provider, so a hit uses no key and works even when every key is down.
- **Cache identity** is LiteLLM's key over **model + the full message list** (system prompt + history + new message):
  - The **session ID is not part of it**. It's never passed as `user` or anything else LiteLLM hashes.
  - The **API key is not part of it**. LiteLLM excludes it.
  - Inside a Router, LiteLLM keys the cache by *model group*, and here every key is its own group. A reply produced by key_2 would then never be a hit for a request starting at key_1. A single **caching group** across all key groups (`caching_groups=[("key_1","key_2")]`) makes them share one cache. Regression test: `test_reply_from_key2_after_real_failure_is_shared_cache`.
- A hit returns the original reply and the **original** stored usage, with `key_id: null`, `fallback_attempts: 0` and `resolution_source: "LLM_CACHE"`.
- **Dependency gotcha:** on every cache *hit*, litellm 1.110.x imports its proxy modules, which need `orjson` and `soundfile`. LiteLLM doesn't declare either. Without them a hit crashes, and behind the Router that crash looks like a key failure, so a cached prompt would get a 503. Both are pinned in `requirements.txt`. At startup the app imports that code path, which checks the dependencies (`/health` reports `cache_enabled: false` if they're missing) and pre-loads the modules so the first real hit is fast.
- Trade-offs: the cache lives in the process, so the backend runs **one uvicorn worker**. It's cleared on restart. Conversation history is persistent; the cache is not, by design.

### SQLite session storage
- The `messages(id, session_id, role, content, metadata, created_at)` table follows the required schema, plus the index `idx_messages_session(session_id, id)`. `metadata` is a JSON string that only assistant rows have. `created_at` is an ISO-8601 UTC timestamp.
- An extra `sessions(session_id, system_prompt, created_at)` table stores an optional custom system prompt per session (bonus feature). The system prompt is never stored as a message and never returned by the history endpoint.
- In Docker, `DATABASE_URL=sqlite:////data/app.db` lives on the named volume `app_data`. WAL mode is on. The schema is created on startup.
- `GET /sessions/{id}/messages` returns messages oldest first, and returns `404 {"detail":"session not found"}` for an unknown session.

### Latency and tokens
- `latency_ms` is measured on the server with a monotonic clock (`time.perf_counter`). It runs from the start of the handler until the reply is ready, so it includes the history read and the cache lookup.
- `input_tokens` and `output_tokens` come from the provider's `usage` for **this request only**. Input covers the system prompt, the history and the new message. Output covers only the reply.
- If a provider omits `usage` or sends invalid values (null, negative, non-integer), LiteLLM's tokenizer estimates only the missing half, and a warning is logged. If the tokenizer itself fails, the count is reported as 0 instead of failing a good reply.

## 4. Verification: how to see failover, cache hits and per-message token usage

> Windows PowerShell: type `curl.exe`, not `curl`, or use Git Bash.

```bash
API=http://localhost:8000

# health
curl $API/health
# {"status":"ok","keys_configured":2,"cache_enabled":true}

# live call
curl -s -X POST $API/chat -H "Content-Type: application/json" \
  -d '{"session_id":"demo-1","message":"Explain AI in one sentence"}'
# metadata.resolution_source = LIVE_INFERENCE, key_id = key_1, fallback_attempts = 0

# cache hit: same first message, NEW session
curl -s -X POST $API/chat -H "Content-Type: application/json" \
  -d '{"session_id":"demo-2","message":"Explain AI in one sentence"}'
# resolution_source = LLM_CACHE, identical reply, same tokens, key_id = null, lower latency_ms

# failover: key_1 rate-limited -> key_2 answers with a real reply
curl -s -X POST $API/chat -H "Content-Type: application/json" \
  -H "X-Simulate-Failure: key_1=429" \
  -d '{"session_id":"demo-3","message":"Name three planets"}'
# key_id = key_2, fallback_attempts = 1

# every key down -> 503, nothing stored
curl -s -i -X POST $API/chat -H "Content-Type: application/json" \
  -H "X-Simulate-Failure: *=429" \
  -d '{"session_id":"demo-4","message":"hello"}'
# HTTP/1.1 503  {"detail":"all providers unavailable"}
curl -s -i $API/sessions/demo-4/messages     # 404

# multi-turn + per-message tokens
curl -s -X POST $API/chat -H "Content-Type: application/json" \
  -d '{"session_id":"demo-5","message":"What is Python?"}'
curl -s -X POST $API/chat -H "Content-Type: application/json" \
  -d '{"session_id":"demo-5","message":"What are its advantages?"}'
curl -s $API/sessions/demo-5/messages
# 4 messages oldest first; each assistant message carries its own input/output tokens

# persistence across restarts
make down && make up
curl -s $API/sessions/demo-5/messages        # still there
```

In the UI, every assistant reply shows a LIVE_INFERENCE or LLM_CACHE badge, plus the model, latency, input/output tokens and the key used, with the failover count when one happened. Errors (422/503) appear as a message in the conversation.

The automated tests are in `backend/tests/`. They cover health, validation, failover with both simulated and real LiteLLM exceptions, cache identity, sessions, tokens, persistence and log redaction. They replace only LiteLLM's innermost provider call, so the Router, its fallback chain, the simulation callback and the built-in cache all run for real.

## 5. Setup Used

- OS: `TODO`
- Editor: `TODO`
- Languages: Python 3.13, JavaScript (React 19, Vite 8)
- Key libraries: FastAPI, SQLAlchemy 2, LiteLLM, Pydantic 2, pytest
- AI assistants: Claude (Anthropic) for architecture review, code generation and tests. `TODO: add any others you used`
- Docs: FastAPI, LiteLLM, SQLAlchemy, Vite, Docker docs

## 6. Bonus features (if any)

- **Custom system prompt per session** (`system_prompt` in `POST /chat`, the `system-prompt-input` field in the UI). It's persisted in the `sessions` table and is part of the cache identity.
- **New chat button**: starts a fresh session without reloading the page.
- **Error classification**: failover covers 401/403, timeouts and empty replies, beyond the required 429/5xx. Request-level errors stop the loop instead of using up every key.
- **No cooldown poisoning**: Router cooldowns are disabled, so one request's failure never changes key selection for the next one.
- **Cache-first resilience**: cached prompts are still answered when every key is down.
- **Health is honest**: it returns 503 `degraded` if the DB is unreachable or fewer than two keys are configured.
- Secret redaction in all logs, including LiteLLM's.
- Character counter near the 4000 limit. A failed message stays visible, marked as not saved.
