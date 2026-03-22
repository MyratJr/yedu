# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Project overview

**Yedu AI Service** — a Python 3.11+ FastAPI microservice that adds natural-language ride booking to the Yedu taxi platform. It sits between the Go backend and LLM providers, processing text/voice/image input and returning structured ride orders via streaming responses.

> The repository currently contains only a specification README. All code must be created following the architecture described here and in README.md.

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
bash scripts/generate_proto.sh
# Or manually:
python -m grpc_tools.protoc -I app/proto --python_out=app/proto --grpc_python_out=app/proto app/proto/chat.proto

# Start all services (Redis + LiteLLM proxy + app)
docker compose -f docker/docker-compose.yml up
```

---

## Architecture

```
KMP Mobile App
      │  REST + SSE (multipart up, SSE down)
      ▼
Go Backend  (auth, orders, driver dispatch)
      │  gRPC bidirectional streaming
      ▼
Python AI Service  ← this repo
  ├── Whisper STT
  ├── Input Router & Tools
  └── LiteLLM Proxy (port 4000, key rotation)
      │  HTTPS
      ▼
OpenAI │ Claude │ Gemini │ Ollama
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
├── main.py              # FastAPI entry point; starts gRPC server alongside HTTP
├── config.py            # Pydantic Settings (reads from .env)
├── api/                 # HTTP health + debug endpoints
├── grpc_server/
│   ├── server.py        # gRPC server bootstrap
│   └── chat_servicer.py # Implements Chat() and ProvideLocation() RPCs
├── proto/               # chat.proto + generated chat_pb2.py / chat_pb2_grpc.py
├── core/
│   ├── router.py        # Detects input type (text/voice/image) and dispatches
│   ├── llm_client.py    # LiteLLM wrapper; handles streaming + provider fallback
│   ├── prompt_builder.py# Assembles system prompt (English/Arabic) + conversation history
│   ├── response_parser.py # Parses LLM output → OrderDraft Pydantic model
│   └── stream_handler.py  # Formats gRPC stream chunks (text, order_draft, action, error)
├── tools/
│   ├── places_search.py # Google Places API lookup
│   ├── geocode.py       # Forward/reverse geocoding
│   └── device_location.py # Emits ActionRequest(REQUEST_GPS) to client
├── processors/
│   ├── voice.py         # Whisper STT (local or OpenAI API mode)
│   ├── image.py         # Base64-encodes images for vision models
│   └── text.py          # Text preprocessing
├── session/
│   └── manager.py       # Redis-backed conversation history (30-min TTL, last 20 msgs)
└── models/
    ├── chat.py          # ChatRequest, ChatResponse Pydantic models
    ├── order.py         # OrderDraft, Stop, Location
    └── tools.py         # Tool definitions for LLM function calling
```

---

## Key design decisions

**gRPC + HTTP dual server:** `app/main.py` must start both the FastAPI ASGI server (uvicorn) and the gRPC server (asyncio) in the same process. Use `asyncio.gather()` or a startup event.

**Streaming flow:** The gRPC `Chat()` RPC streams `ChatResponse` messages of type `TextChunk`, `OrderDraft`, `ActionRequest`, or `ErrorInfo`. The Go backend proxies these to the mobile client as SSE events with matching types: `text`, `order_draft`, `action`, `error`.

**Tool-calling loop:** `llm_client.py` runs a loop — call LLM → if response contains tool calls, execute them → feed results back → repeat — until the LLM returns a final text response containing the order draft.

**LiteLLM proxy vs. direct:** For multi-key rotation and load balancing across providers, traffic goes through the LiteLLM proxy (`LITELLM_PROXY_URL`). Direct key usage (`OPENAI_API_KEY` etc.) is the fallback for simple single-key setups.

**Whisper modes:** `WHISPER_MODE=local` loads the model in-process (GPU/CPU); `WHISPER_MODE=api` calls OpenAI's transcription endpoint. Switch via env var — no code change needed.

**Session TTL:** Redis keys expire after `SESSION_TTL_SECONDS` (default 1800). The session manager stores the last 20 messages and the user's last known location (5-min TTL).

**Proto generation:** `chat_pb2.py` and `chat_pb2_grpc.py` are generated — never edit them manually. Re-run `generate_proto.sh` after any `.proto` change.

---

## Configuration reference

All settings are in `app/config.py` via `pydantic-settings` and loaded from `.env`:

| Variable | Default | Purpose |
|---|---|---|
| `SERVICE_HOST` | `0.0.0.0` | HTTP bind address |
| `SERVICE_PORT` | `8100` | HTTP port |
| `GRPC_PORT` | `50051` | gRPC port |
| `ENV` | `development` | `development` or `production` |
| `REDIS_URL` | `redis://localhost:6379/0` | Session store |
| `LITELLM_PROXY_URL` | `http://localhost:4000` | LLM proxy |
| `GOOGLE_PLACES_API_KEY` | — | Location resolution |
| `WHISPER_MODEL` | `base` | `tiny`/`base`/`small`/`medium`/`large` |
| `WHISPER_MODE` | `local` | `local` or `api` |
| `SESSION_TTL_SECONDS` | `1800` | Redis session expiry |

---

## Testing

- Framework: `pytest` + `pytest-asyncio`
- Use mock LLM client and tool mocks in `tests/conftest.py`
- gRPC tests use an in-process test server
- HTTP tests use `httpx.AsyncClient` with the FastAPI `app` directly
