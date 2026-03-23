# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Project overview

**Yedu AI Service** — a Python 3.11+ FastAPI microservice that adds natural-language ride booking to the Yedu taxi platform. It sits between the Go backend and LLM providers, processing text/voice/image input and returning structured ride orders via gRPC streaming.

---

## Development commands

```bash
# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate          # Linux/Mac
# .venv\Scripts\activate           # Windows

# Install dependencies
pip install -r requirements.txt

# Run the service (HTTP on 8100, gRPC on 50051)
uvicorn app.main:app --host 0.0.0.0 --port 8100 --reload

# Run tests
pytest

# Run a single test file
pytest tests/test_router.py -v

# Run a single test
pytest tests/test_router.py::test_function_name -v

# Regenerate protobuf Python stubs from chat.proto
bash scripts/generate_stubs.sh
# Or manually:
python -m grpc_tools.protoc -I app/proto --python_out=app/proto --grpc_python_out=app/proto app/proto/chat.proto

# Start all services (Redis + LiteLLM proxy + app)
docker compose -f docker/docker-compose.yml up
```

---

## Architecture

```
KMP Mobile App
      │  REST + SSE
      ▼
Go Backend  (auth, orders, driver dispatch)
      │  gRPC bidirectional streaming  :50051
      ▼
Yedu AI Service  ← this repo
  ├── Input Router  (text / voice / image)
  ├── Whisper STT
  ├── LLM Client  (tool-calling loop)
  │     └── Tools: Places Search, Geocoding, GPS Request
  ├── Session Manager  (Redis)
  └── LiteLLM Proxy  :4000  (key rotation, multi-provider)
        │  HTTPS
        ▼
  Gemini │ Claude │ GPT-4 │ Ollama
```

**Communication protocols:**
- Mobile ↔ Go Backend: REST + SSE
- Go Backend ↔ AI Service: gRPC (port 50051), bidirectional streaming
- AI Service ↔ LLM providers: HTTPS via LiteLLM proxy (port 4000)
- AI Service ↔ Redis: session state (port 6379)

---

## Code structure

```
app/
├── main.py                  # FastAPI entry point; starts gRPC + HTTP in same process
├── api/
│   └── routes.py            # Health, readiness, and debug HTTP endpoints
├── core/
│   ├── config.py            # Pydantic Settings — reads from .env
│   ├── router.py            # Orchestrates input → LLM → order draft pipeline
│   ├── llm_client.py        # LiteLLM wrapper; tool-calling loop; multi-model fallback
│   ├── prompt_builder.py    # Builds system prompt + history messages (EN/AR)
│   └── stream_handler.py    # Converts events → gRPC ChatResponse messages
├── grpc_server/
│   └── server.py            # gRPC server bootstrap
├── proto/
│   ├── chat.proto           # Source of truth for gRPC contract
│   ├── chat_pb2.py          # Generated — do not edit
│   └── chat_pb2_grpc.py     # Generated — do not edit
├── models/
│   ├── chat.py              # ChatRequest, ChatResponse, InputType
│   └── tools.py             # Tool definitions (OpenAI function-calling format)
├── processors/
│   ├── voice.py             # Whisper STT — local (faster-whisper) or OpenAI API
│   ├── image.py             # Encodes image bytes → base64 data URL for vision models
│   └── text.py              # Normalises whitespace
├── session/
│   └── manager.py           # Redis-backed history (last 20 msgs, 30-min TTL)
└── tools/
    ├── places_search.py     # Google Places API — returns top 3 results
    └── geocode.py           # Forward + reverse geocoding via Google Maps API

tests/
├── conftest.py              # Shared fixtures (mock LLM, mock Redis, test gRPC server)
├── test_api.py              # HTTP endpoint tests
├── test_response_parser.py  # Order draft extraction tests
└── test_session.py          # Session manager tests

scripts/
└── generate_stubs.sh        # Regenerates chat_pb2.py and chat_pb2_grpc.py from chat.proto
```

---

## Key design decisions

**gRPC + HTTP dual server:** `app/main.py` starts both the FastAPI ASGI server (uvicorn) and the gRPC server in the same process via FastAPI's lifespan context manager using `asyncio.gather()`.

**Streaming flow:** The gRPC `Chat()` RPC streams `ChatResponse` messages of type `TextChunk`, `ActionRequest`, or `ErrorInfo`. The Go backend proxies these to the mobile client as SSE events with matching types: `text`, `order_draft`, `action`, `error`.

**Tool-calling loop:** `llm_client.py` runs up to 5 rounds — call LLM → if response contains tool calls, execute them → feed results back → repeat — until the LLM returns a final response containing the order draft.

**Model fallback chain:** Gemini 2.5 Flash → Gemini 2.0 Flash Lite → Claude Sonnet → GPT-4. First model that responds successfully is used.

**LiteLLM proxy vs. direct:** Traffic goes through the LiteLLM proxy (`LITELLM_PROXY_URL`) for multi-key rotation. Direct API keys (`OPENAI_API_KEY` etc.) are the fallback for single-key setups.

**Whisper modes:** `WHISPER_MODE=local` loads faster-whisper in-process (GPU/CPU); `WHISPER_MODE=api` calls OpenAI's transcription endpoint. Switch via env var — no code change needed.

**Proto generation:** `chat_pb2.py` and `chat_pb2_grpc.py` are generated — never edit them manually. Re-run `scripts/generate_stubs.sh` after any `.proto` change.

---

## Configuration reference

All settings are in `app/core/config.py` via `pydantic-settings` and loaded from `.env`:

| Variable | Default | Purpose |
|---|---|---|
| `SERVICE_HOST` | `0.0.0.0` | HTTP bind address |
| `SERVICE_PORT` | `8100` | HTTP port |
| `GRPC_PORT` | `50051` | gRPC port |
| `ENV` | `development` | `development` or `production` |
| `REDIS_URL` | `redis://localhost:6379/0` | Session store |
| `LITELLM_PROXY_URL` | `http://localhost:4000` | LLM proxy |
| `OPENAI_API_KEY` | — | OpenAI key |
| `ANTHROPIC_API_KEY` | — | Claude key |
| `GEMINI_API_KEY` | — | Gemini key |
| `GOOGLE_PLACES_API_KEY` | — | Places + Geocoding |
| `WHISPER_MODEL` | `base` | `tiny`/`base`/`small`/`medium`/`large` |
| `WHISPER_MODE` | `local` | `local` or `api` |

---

## Testing

- Framework: `pytest` + `pytest-asyncio`
- Mock LLM client and tool mocks in `tests/conftest.py`
- gRPC tests use an in-process test server
- HTTP tests use `httpx.AsyncClient` with the FastAPI `app` directly
