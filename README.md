# Yedu AI Service

> Python 3.11+ microservice that adds natural-language ride booking to the Yedu taxi platform.
> Sits between the Go backend and LLM providers — processes text, voice, and image input, then returns structured ride orders via gRPC streaming.

---

## Table of contents

1. [Architecture](#1-architecture)
2. [Project structure](#2-project-structure)
3. [How it works](#3-how-it-works)
4. [Setup](#4-setup)
5. [Configuration](#5-configuration)
6. [Running the service](#6-running-the-service)
7. [API reference](#7-api-reference)
8. [Testing](#8-testing)
9. [Proto reference](#9-proto-reference)

---

## 1. Architecture

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

**Ports:**
| Service | Port |
|---|---|
| HTTP (FastAPI) | 8100 |
| gRPC | 50051 |
| LiteLLM proxy | 4000 |
| Redis | 6379 |

Both the HTTP and gRPC servers run in the **same process** — started together via FastAPI's lifespan context manager using `asyncio.gather()`.

---

## 2. Project structure

```
app/
├── main.py                  # FastAPI entry point; starts gRPC + HTTP together
├── api/
│   └── routes.py            # Health, readiness, and debug HTTP endpoints
├── core/
│   ├── config.py            # Pydantic Settings — reads from .env
│   ├── router.py            # Orchestrates input → LLM → order draft pipeline
│   ├── llm_client.py        # LiteLLM wrapper; tool-calling loop; multi-model fallback
│   ├── prompt_builder.py    # Builds system prompt + history messages (EN/AR)
│   ├── response_parser.py   # Extracts OrderDraft from <order_draft>...</order_draft> tags
│   └── stream_handler.py    # Converts events → gRPC ChatResponse messages
├── grpc_server/
│   ├── server.py            # gRPC server bootstrap
│   └── chat_servicer.py     # Implements Chat() and ProvideLocation() RPCs
├── proto/
│   ├── chat.proto           # Source of truth for gRPC contract
│   ├── chat_pb2.py          # Generated — do not edit
│   └── chat_pb2_grpc.py     # Generated — do not edit
├── models/
│   ├── chat.py              # ChatRequest, ChatResponse, InputType
│   ├── order.py             # OrderDraft, Location, Stop
│   └── tools.py             # Tool definitions (OpenAI function-calling format)
├── processors/
│   ├── voice.py             # Whisper STT — local (faster-whisper) or OpenAI API
│   ├── image.py             # Encodes image bytes → base64 data URL for vision models
│   └── text.py              # Normalises whitespace
├── session/
│   └── manager.py           # Redis-backed history (last 20 msgs, 30-min TTL)
└── tools/
    ├── places_search.py     # Google Places API — returns top 3 results
    ├── geocode.py           # Forward + reverse geocoding via Google Maps API
    └── device_location.py   # Emits REQUEST_GPS action to mobile client

tests/
├── conftest.py              # Shared fixtures (mock LLM, mock Redis, test gRPC server)
├── test_api.py              # HTTP endpoint tests
├── test_response_parser.py  # Order draft extraction tests
└── test_session.py          # Session manager tests

scripts/
└── generate_stubs.sh        # Regenerates chat_pb2.py and chat_pb2_grpc.py from chat.proto
```

---

## 3. How it works

### Input pipeline

```
ChatRequest (text | audio | image)
        │
        ▼
  processors/
    voice.py  → Whisper STT → plain text
    image.py  → base64 data URL (passed to vision model)
    text.py   → normalise whitespace
        │
        ▼
  session/manager.py  → load conversation history + last known GPS from Redis
        │
        ▼
  core/prompt_builder.py  → build [system_prompt, ...history, user_message]
        │
        ▼
  core/llm_client.py  → stream LLM response
```

### LLM tool-calling loop

The LLM can invoke tools during a response. `llm_client.py` runs up to **5 rounds**:

```
Call LLM
  └─ if tool_calls in response:
       execute tool(s):
         search_places(query, language)
         geocode_address(address)
         reverse_geocode(lat, lng)
         request_user_location()   ← sends REQUEST_GPS action to mobile
       feed results back → repeat
  └─ final text response
```

### Model fallback chain

```
Gemini 2.5 Flash → Gemini 2.0 Flash Lite → Claude Sonnet → GPT-4
```

The first model that responds successfully is used; the rest are skipped.

### Order draft extraction

The LLM wraps structured output in XML-like tags:

```
<order_draft>
{
  "pickup":      { "address": "Dubai Mall", "latitude": 25.1972, "longitude": 55.2797 },
  "destination": { "address": "DXB Airport", "latitude": 25.2532, "longitude": 55.3657 },
  "ride_type":   "standard",
  "notes":       ""
}
</order_draft>
```

`response_parser.py` extracts and validates this into an `OrderDraft` model. The tag is stripped before the text chunk is streamed to the user.

### gRPC streaming response types

Each `ChatResponse` carries exactly one of:

| Type | When |
|---|---|
| `TextChunk` | Streaming text from the LLM |
| `OrderDraftMsg` | Structured ride order ready for confirmation |
| `ActionRequest(REQUEST_GPS)` | AI needs the user's device location |
| `ActionRequest(CONFIRM_ORDER)` | AI asks user to confirm the order |
| `ErrorInfo` | Something went wrong |

### Session storage (Redis)

- **Conversation history:** last 20 messages, TTL = 30 min (`SESSION_TTL_SECONDS`)
- **User location:** stored separately after `ProvideLocation()` RPC, TTL = 5 min
- Key format: `session:{session_id}:messages`, `session:{session_id}:location`

---

## 4. Setup

```bash
# Clone and enter repo
git clone <repo-url>
cd ai-chat-service

# Create virtual environment
python -m venv .venv
source .venv/bin/activate        # Linux/Mac
# .venv\Scripts\activate         # Windows

# Install dependencies
pip install -r requirements.txt

# Copy env template and fill in your keys
cp .env.example .env
```

### With Docker (recommended)

```bash
docker compose -f docker/docker-compose.yml up
```

Starts Redis + LiteLLM proxy + the AI service together.

---

## 5. Configuration

All settings live in `.env` and are loaded by `app/core/config.py`:

| Variable | Default | Description |
|---|---|---|
| `SERVICE_HOST` | `0.0.0.0` | HTTP bind address |
| `SERVICE_PORT` | `8100` | HTTP port |
| `GRPC_PORT` | `50051` | gRPC port |
| `ENV` | `development` | `development` or `production` |
| `REDIS_URL` | `redis://localhost:6379/0` | Session store |
| `LITELLM_PROXY_URL` | `http://localhost:4000` | LLM proxy URL |
| `OPENAI_API_KEY` | — | OpenAI key (fallback if no proxy) |
| `ANTHROPIC_API_KEY` | — | Claude key |
| `GEMINI_API_KEY` | — | Gemini key |
| `GOOGLE_PLACES_API_KEY` | — | Places + Geocoding |
| `WHISPER_MODEL` | `base` | `tiny` / `base` / `small` / `medium` / `large` |
| `WHISPER_MODE` | `local` | `local` (faster-whisper) or `api` (OpenAI) |
| `SESSION_TTL_SECONDS` | `1800` | Redis session expiry (seconds) |

---

## 6. Running the service

```bash
# HTTP on :8100, gRPC on :50051
uvicorn app.main:app --host 0.0.0.0 --port 8100 --reload

# Regenerate protobuf stubs after editing chat.proto
bash scripts/generate_stubs.sh
```

---

## 7. API reference

### HTTP endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness probe — returns `{ "status": "ok" }` |
| `GET` | `/ready` | Readiness probe — checks Redis connectivity |
| `GET` | `/debug/session/{session_id}` | Inspect session history + stored location |
| `DELETE` | `/debug/session/{session_id}` | Clear session data |

### gRPC — `ChatService`

Defined in [app/proto/chat.proto](app/proto/chat.proto).

#### `Chat` — bidirectional streaming

```
rpc Chat(stream ChatRequest) returns (stream ChatResponse)
```

**ChatRequest fields:**

| Field | Type | Description |
|---|---|---|
| `session_id` | string | Unique conversation ID |
| `user_id` | string | Passenger ID |
| `text_input` | string | Plain text message |
| `audio_input` | bytes | Raw audio bytes (WAV/MP3) |
| `image_input` | bytes | Image bytes (JPEG/PNG) |
| `language` | string | `en` or `ar` (default `en`) |

Only one of `text_input`, `audio_input`, or `image_input` should be set per message.

**ChatResponse** carries one of: `TextChunk`, `OrderDraftMsg`, `ActionRequest`, `ErrorInfo`.

#### `ProvideLocation` — unary

```
rpc ProvideLocation(LocationPayload) returns (LocationAck)
```

Called by the Go backend after the mobile client returns GPS coordinates in response to a `REQUEST_GPS` action. Stores the location in Redis for the next LLM turn.

---

## 8. Testing

```bash
# Run all tests
pytest

# Specific file
pytest tests/test_router.py -v

# Single test
pytest tests/test_router.py::test_function_name -v
```

Test fixtures in `tests/conftest.py` mock the LLM client, Redis, and tools. gRPC tests spin up an in-process server.

---

## 9. Proto reference

Edit [app/proto/chat.proto](app/proto/chat.proto), then regenerate stubs:

```bash
bash scripts/generate_stubs.sh

# Or manually:
python -m grpc_tools.protoc \
  -I app/proto \
  --python_out=app/proto \
  --grpc_python_out=app/proto \
  app/proto/chat.proto
```

**Never edit `chat_pb2.py` or `chat_pb2_grpc.py` by hand** — they are overwritten on every generation.
