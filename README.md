# Yedu AI Service — Developer Documentation

> **Audience:** Python developer building the AI microservice  
> **Last updated:** March 2026  
> **Service name:** `yedu-ai-service`  
> **Language:** Python 3.11+  
> **Framework:** FastAPI  

---

## Table of contents

1. [Project overview](#1-project-overview)
2. [Architecture & system context](#2-architecture--system-context)
3. [Environment setup](#3-environment-setup)
4. [Project structure](#4-project-structure)
5. [Phase 1 — Core service & LiteLLM integration](#5-phase-1--core-service--litellm-integration)
6. [Phase 2 — Multi-modal input processing](#6-phase-2--multi-modal-input-processing)
7. [Phase 3 — Tool calling & location resolution](#7-phase-3--tool-calling--location-resolution)
8. [Phase 4 — Token queue & multi-provider setup](#8-phase-4--token-queue--multi-provider-setup)
9. [Phase 5 — Order confirmation flow](#9-phase-5--order-confirmation-flow)
10. [Phase 6 — Production hardening](#10-phase-6--production-hardening)
11. [API reference](#11-api-reference)
12. [Configuration reference](#12-configuration-reference)
13. [What to ask from the Go backend developer](#13-what-to-ask-from-the-go-backend-developer)
14. [What to ask from the mobile (KMP) developer](#14-what-to-ask-from-the-mobile-kmp-developer)
15. [Connecting all three services together](#15-connecting-all-three-services-together)

---

## 1. Project overview

The Yedu AI Service is a **standalone Python microservice** that adds natural-language ride booking to the Yedu taxi platform. It sits between the existing Go backend and the LLM providers (OpenAI, Claude, Gemini, Ollama), processing passenger messages — text, voice, and images — and returning structured ride orders via streaming markdown responses.

### What this service does

- Accepts multi-modal input (text + images + voice) in a single request
- Transcribes voice messages to text (Whisper)
- Understands natural language ride requests ("Take me from the airport to Burj Khalifa")
- Resolves location names to coordinates via Google Places API
- Triggers client-side GPS when user says "from my location"
- Supports multi-stop routes in a single prompt
- Streams responses as markdown via SSE (Server-Sent Events)
- Returns a structured order draft JSON for user confirmation
- Abstracts all LLM providers behind a single interface (LiteLLM)
- Rotates API keys automatically via a token queue

### What this service does NOT do

- It does not handle authentication — the Go backend does that
- It does not create orders — it produces a draft; the Go backend creates the order after user confirmation
- It does not manage payments, driver dispatch, or any existing business logic
- It does not store conversation history long-term — it uses Redis for session-scoped memory only

---

## 2. Architecture & system context

```
┌─────────────────────────────────────────────────────────┐
│                   KMP Mobile App                        │
│  (text input, voice recorder, image picker, SSE client) │
└──────────────────────┬──────────────────────────────────┘
                       │  REST + Multipart + SSE
                       ▼
┌─────────────────────────────────────────────────────────┐
│                   Go Backend                            │
│  (auth, orders, payments, driver dispatch)              │
│  NEW: /api/v1/ai/chat proxy endpoint                   │
└──────────────────────┬──────────────────────────────────┘
                       │  gRPC (bidirectional streaming)
                       ▼
┌─────────────────────────────────────────────────────────┐
│              Python AI Service (this repo)              │
│  ┌──────────┐ ┌──────────┐ ┌───────────────────────┐   │
│  │ Whisper  │ │ Router   │ │ LiteLLM Proxy         │   │
│  │ STT      │ │ & Tools  │ │ (token queue,         │   │
│  │          │ │          │ │  load balancing)       │   │
│  └──────────┘ └──────────┘ └───────────────────────┘   │
└──────────────────────┬──────────────────────────────────┘
                       │  HTTPS
                       ▼
        ┌──────┬───────┬────────┬────────┐
        │OpenAI│ Claude│ Gemini │ Ollama │
        └──────┘───────┘────────┘────────┘
```

### Communication protocols

| From → To | Protocol | Format |
|---|---|---|
| Mobile → Go backend | REST + SSE | Multipart form data (up), SSE stream (down) |
| Go backend → AI service | gRPC | Protobuf with bidirectional streaming |
| AI service → LLM providers | HTTPS | JSON (OpenAI-compatible via LiteLLM) |
| AI service → Google Places | HTTPS | JSON |
| AI service → Redis | TCP | Redis protocol |

---

## 3. Environment setup

### 3.1 Prerequisites

```bash
# Required
python >= 3.11
pip >= 23.0
docker >= 24.0
docker-compose >= 2.20
redis >= 7.0

# Optional (for local Ollama)
ollama >= 0.1.0

# For gRPC code generation
protoc >= 3.21
grpcio-tools (installed via pip)
```

### 3.2 Create the project

```bash
mkdir yedu-ai-service && cd yedu-ai-service
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows
```

### 3.3 Install dependencies

Create `requirements.txt`:

```txt
# Core framework
fastapi==0.115.6
uvicorn[standard]==0.34.0
python-multipart==0.0.18

# LLM abstraction
litellm==1.55.8

# gRPC
grpcio==1.68.1
grpcio-tools==1.68.1
protobuf==5.29.2

# Voice processing
openai-whisper==20240930
# OR for API-based: openai>=1.58.0

# Async HTTP client
httpx==0.28.1

# Redis for session state
redis[hiredis]==5.2.1

# Configuration
pydantic-settings==2.7.1

# Image processing
Pillow==11.1.0

# Streaming
sse-starlette==2.2.1

# Logging & monitoring
structlog==24.4.0
prometheus-fastapi-instrumentator==7.0.2

# Testing
pytest==8.3.4
pytest-asyncio==0.25.0
httpx==0.28.1  # also used for test client
```

```bash
pip install -r requirements.txt
```

### 3.4 Environment variables

Create `.env` file:

```env
# Service
SERVICE_HOST=0.0.0.0
SERVICE_PORT=8100
ENV=development
LOG_LEVEL=debug

# Redis
REDIS_URL=redis://localhost:6379/0

# LiteLLM Proxy (if running separately)
LITELLM_PROXY_URL=http://localhost:4000

# API Keys (for direct LiteLLM usage)
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
GEMINI_API_KEY=AIza...

# Google Places
GOOGLE_PLACES_API_KEY=AIza...

# Whisper
WHISPER_MODEL=base        # tiny, base, small, medium, large
WHISPER_MODE=local        # local or api
OPENAI_API_KEY_WHISPER=sk-...  # only if WHISPER_MODE=api

# gRPC
GRPC_PORT=50051

# Session
SESSION_TTL_SECONDS=1800  # 30 min conversation timeout
```

---

## 4. Project structure

```
yedu-ai-service/
├── app/
│   ├── __init__.py
│   ├── main.py                  # FastAPI app entry point
│   ├── config.py                # Pydantic settings
│   │
│   ├── api/                     # HTTP endpoints (health, debug)
│   │   ├── __init__.py
│   │   ├── health.py
│   │   └── routes.py
│   │
│   ├── grpc_server/             # gRPC service implementation
│   │   ├── __init__.py
│   │   ├── server.py            # gRPC server bootstrap
│   │   └── chat_servicer.py     # ChatService implementation
│   │
│   ├── proto/                   # Protobuf definitions (shared with Go)
│   │   ├── chat.proto
│   │   ├── chat_pb2.py          # Generated
│   │   └── chat_pb2_grpc.py     # Generated
│   │
│   ├── core/                    # Core AI logic
│   │   ├── __init__.py
│   │   ├── router.py            # Input type detection & dispatch
│   │   ├── llm_client.py        # LiteLLM wrapper
│   │   ├── prompt_builder.py    # System prompts & context assembly
│   │   ├── response_parser.py   # Parse LLM output → order draft
│   │   └── stream_handler.py    # SSE stream formatting
│   │
│   ├── tools/                   # LLM function-calling tools
│   │   ├── __init__.py
│   │   ├── base.py              # Base tool interface
│   │   ├── places_search.py     # Google Places API
│   │   ├── geocode.py           # Reverse/forward geocoding
│   │   └── device_location.py   # Trigger client GPS
│   │
│   ├── processors/              # Input processors
│   │   ├── __init__.py
│   │   ├── voice.py             # Whisper STT
│   │   ├── image.py             # Image encoding for vision models
│   │   └── text.py              # Text preprocessing
│   │
│   ├── session/                 # Conversation state
│   │   ├── __init__.py
│   │   └── manager.py           # Redis-backed session store
│   │
│   └── models/                  # Pydantic models
│       ├── __init__.py
│       ├── chat.py              # ChatRequest, ChatResponse
│       ├── order.py             # OrderDraft, Location, Stop
│       └── tools.py             # Tool definitions
│
├── litellm_config/
│   └── config.yaml              # LiteLLM Proxy configuration
│
├── tests/
│   ├── conftest.py
│   ├── test_router.py
│   ├── test_llm_client.py
│   ├── test_tools.py
│   ├── test_voice.py
│   └── test_grpc.py
│
├── docker/
│   ├── Dockerfile
│   ├── Dockerfile.litellm
│   └── docker-compose.yml
│
├── scripts/
│   ├── generate_proto.sh
│   └── seed_test_data.py
│
├── .env
├── .env.example
├── requirements.txt
├── pyproject.toml
└── README.md
```

---

## 5. Phase 1 — Core service & LiteLLM integration

> **Goal:** A running FastAPI service that accepts a text message via gRPC, sends it to an LLM through LiteLLM, and streams the response back.

### 5.1 Configuration

```python
# app/config.py
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # Service
    service_host: str = "0.0.0.0"
    service_port: int = 8100
    env: str = "development"
    log_level: str = "info"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # LiteLLM
    litellm_proxy_url: Optional[str] = None
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    gemini_api_key: Optional[str] = None
    default_model: str = "gpt-4o"
    fallback_models: list[str] = ["claude-sonnet-4-20250514", "gemini/gemini-2.0-flash"]

    # Google Places
    google_places_api_key: str = ""

    # Whisper
    whisper_model: str = "base"
    whisper_mode: str = "local"  # "local" or "api"

    # gRPC
    grpc_port: int = 50051

    # Session
    session_ttl_seconds: int = 1800

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
```

### 5.2 Protobuf definition

This is the contract between Go backend and Python AI service. **You must agree on this file with the Go developer before writing any code.**

```protobuf
// app/proto/chat.proto
syntax = "proto3";

package yedu.ai.v1;

option go_package = "github.com/yedu/backend/pkg/ai/v1;aiv1";

service ChatService {
  // Bidirectional streaming: Go sends request, Python streams back chunks
  rpc Chat (ChatRequest) returns (stream ChatResponse);

  // Client location callback: mobile resolved GPS, Go forwards it here
  rpc ProvideLocation (LocationUpdate) returns (LocationAck);
}

// --- Request ---

message ChatRequest {
  string session_id = 1;          // Unique conversation session
  string user_id = 2;             // Authenticated user ID (from Go)
  string language = 3;            // "en" or "ar"

  // Multi-modal content (at least one must be present)
  string text = 4;                // Text message (may be empty if voice-only)
  repeated bytes images = 5;      // JPEG/PNG images as raw bytes
  bytes voice = 6;                // Audio file bytes (m4a, wav, mp3)
  string voice_mime_type = 7;     // e.g. "audio/m4a"

  // Context from Go backend
  UserContext user_context = 8;
}

message UserContext {
  string display_name = 1;
  string phone = 2;
  repeated SavedAddress saved_addresses = 3;
  Location last_known_location = 4;  // Last GPS from mobile
}

message SavedAddress {
  string label = 1;               // "Home", "Work"
  Location location = 2;
}

message Location {
  double latitude = 1;
  double longitude = 2;
  string address = 3;             // Human-readable address
  string place_id = 4;            // Google Place ID if available
}

// --- Response (streamed) ---

message ChatResponse {
  oneof payload {
    TextChunk text_chunk = 1;       // Markdown text (streamed token by token)
    OrderDraft order_draft = 2;     // Structured order for confirmation
    ActionRequest action_request = 3; // Request client action (e.g., GPS)
    ErrorInfo error = 4;
  }
}

message TextChunk {
  string content = 1;              // Partial markdown text
  bool is_final = 2;              // True for the last chunk
}

message OrderDraft {
  string draft_id = 1;
  repeated Stop stops = 2;         // Ordered list: pickup → waypoints → dropoff
  string summary = 3;              // Human-readable summary
  string estimated_fare = 4;       // Optional estimate
}

message Stop {
  int32 order = 1;                 // 0 = pickup, last = dropoff, middle = waypoints
  string label = 2;                // "Dubai Airport Terminal 3"
  Location location = 3;
  StopType type = 4;
}

enum StopType {
  PICKUP = 0;
  WAYPOINT = 1;
  DROPOFF = 2;
}

message ActionRequest {
  ActionType type = 1;
  string request_id = 2;           // To correlate with ProvideLocation
  string message = 3;              // Display message: "Fetching your location..."
}

enum ActionType {
  REQUEST_GPS = 0;                 // Ask mobile to send current GPS
}

message LocationUpdate {
  string session_id = 1;
  string request_id = 2;           // Matches ActionRequest.request_id
  Location location = 3;
}

message LocationAck {
  bool success = 1;
}

message ErrorInfo {
  string code = 1;
  string message = 2;
}
```

Generate Python code from proto:

```bash
# scripts/generate_proto.sh
#!/bin/bash
python -m grpc_tools.protoc \
  -I./app/proto \
  --python_out=./app/proto \
  --grpc_python_out=./app/proto \
  ./app/proto/chat.proto
```

### 5.3 LLM client with LiteLLM

```python
# app/core/llm_client.py
import litellm
from litellm import acompletion
from typing import AsyncGenerator
import structlog

from app.config import settings

logger = structlog.get_logger()

# Configure LiteLLM
litellm.set_verbose = settings.env == "development"

# If using LiteLLM Proxy, route all calls through it
if settings.litellm_proxy_url:
    litellm.api_base = settings.litellm_proxy_url


class LLMClient:
    """
    Unified LLM client wrapping all providers through LiteLLM.

    Usage:
        client = LLMClient()
        async for chunk in client.stream_completion(messages, tools):
            print(chunk)
    """

    def __init__(self):
        self.default_model = settings.default_model
        self.fallback_models = settings.fallback_models

    async def stream_completion(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        model: str | None = None,
    ) -> AsyncGenerator[dict, None]:
        """
        Stream a completion from the LLM. Automatically falls back
        to alternative providers on failure.

        Yields dicts with keys:
          - {"type": "text", "content": "..."}
          - {"type": "tool_call", "name": "...", "arguments": {...}}
          - {"type": "finish", "reason": "stop"}
        """
        target_model = model or self.default_model
        models_to_try = [target_model] + [
            m for m in self.fallback_models if m != target_model
        ]

        last_error = None

        for attempt_model in models_to_try:
            try:
                logger.info(
                    "llm_request",
                    model=attempt_model,
                    message_count=len(messages),
                    has_tools=tools is not None,
                )

                response = await acompletion(
                    model=attempt_model,
                    messages=messages,
                    tools=tools,
                    stream=True,
                    temperature=0.3,
                    max_tokens=2048,
                )

                async for chunk in response:
                    delta = chunk.choices[0].delta

                    if delta.content:
                        yield {"type": "text", "content": delta.content}

                    if delta.tool_calls:
                        for tc in delta.tool_calls:
                            if tc.function:
                                yield {
                                    "type": "tool_call",
                                    "id": tc.id,
                                    "name": tc.function.name,
                                    "arguments": tc.function.arguments,
                                }

                    if chunk.choices[0].finish_reason:
                        yield {
                            "type": "finish",
                            "reason": chunk.choices[0].finish_reason,
                        }

                return  # Success — exit the retry loop

            except Exception as e:
                last_error = e
                logger.warning(
                    "llm_fallback",
                    failed_model=attempt_model,
                    error=str(e),
                )
                continue

        # All models failed
        logger.error("llm_all_failed", error=str(last_error))
        yield {
            "type": "error",
            "content": "All AI providers are currently unavailable. Please try again.",
        }

    async def completion_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        tool_executor,
        max_rounds: int = 5,
    ) -> AsyncGenerator[dict, None]:
        """
        Run a multi-turn tool-calling loop.
        The LLM calls tools, we execute them and feed results back,
        until the LLM produces a final text response.
        """
        current_messages = list(messages)

        for round_num in range(max_rounds):
            tool_calls_buffer = {}  # id -> {name, arguments_str}
            text_buffer = []

            async for chunk in self.stream_completion(
                current_messages, tools=tools
            ):
                if chunk["type"] == "text":
                    text_buffer.append(chunk["content"])
                    yield chunk  # Stream text to client immediately

                elif chunk["type"] == "tool_call":
                    tc_id = chunk.get("id")
                    if tc_id:
                        if tc_id not in tool_calls_buffer:
                            tool_calls_buffer[tc_id] = {
                                "name": chunk["name"] or "",
                                "arguments": chunk.get("arguments", ""),
                            }
                        else:
                            tool_calls_buffer[tc_id]["arguments"] += chunk.get(
                                "arguments", ""
                            )

                elif chunk["type"] == "finish":
                    if chunk["reason"] == "tool_calls" and tool_calls_buffer:
                        break
                    else:
                        yield chunk
                        return

                elif chunk["type"] == "error":
                    yield chunk
                    return

            # If we have tool calls, execute them
            if not tool_calls_buffer:
                return

            # Add assistant message with tool calls
            assistant_msg = {
                "role": "assistant",
                "content": "".join(text_buffer) if text_buffer else None,
                "tool_calls": [
                    {
                        "id": tc_id,
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": tc["arguments"],
                        },
                    }
                    for tc_id, tc in tool_calls_buffer.items()
                ],
            }
            current_messages.append(assistant_msg)

            # Execute each tool and add results
            for tc_id, tc in tool_calls_buffer.items():
                logger.info("tool_execute", name=tc["name"])
                result = await tool_executor(tc["name"], tc["arguments"])
                current_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": str(result),
                    }
                )

        yield {
            "type": "error",
            "content": "Too many tool-calling rounds. Please simplify your request.",
        }
```

### 5.4 gRPC server

```python
# app/grpc_server/chat_servicer.py
import json
import grpc
import structlog

from app.proto import chat_pb2, chat_pb2_grpc
from app.core.llm_client import LLMClient
from app.core.prompt_builder import PromptBuilder
from app.core.router import InputRouter
from app.core.response_parser import ResponseParser
from app.tools import ToolRegistry
from app.session.manager import SessionManager

logger = structlog.get_logger()


class ChatServicer(chat_pb2_grpc.ChatServiceServicer):
    def __init__(self):
        self.llm = LLMClient()
        self.prompt_builder = PromptBuilder()
        self.router = InputRouter()
        self.parser = ResponseParser()
        self.tools = ToolRegistry()
        self.sessions = SessionManager()

    async def Chat(self, request, context):
        """
        Main chat endpoint. Receives a ChatRequest, streams back ChatResponse.
        """
        session_id = request.session_id
        user_id = request.user_id
        language = request.language or "en"

        logger.info(
            "chat_request",
            session_id=session_id,
            user_id=user_id,
            has_text=bool(request.text),
            image_count=len(request.images),
            has_voice=bool(request.voice),
        )

        try:
            # Step 1: Process all input modalities
            processed = await self.router.process(
                text=request.text,
                images=list(request.images),
                voice=request.voice,
                voice_mime=request.voice_mime_type,
            )

            # Step 2: Load conversation history from session
            history = await self.sessions.get_history(session_id)

            # Step 3: Build the messages array
            messages = self.prompt_builder.build(
                processed_input=processed,
                user_context=request.user_context,
                history=history,
                language=language,
            )

            # Step 4: Get tool definitions
            tool_defs = self.tools.get_definitions()

            # Step 5: Stream LLM response with tool calling
            full_response = []

            async def execute_tool(name: str, arguments_json: str):
                args = json.loads(arguments_json)

                # Special case: GPS request → send action to client
                if name == "request_user_location":
                    # We need to ask the Go backend / mobile to provide GPS
                    action_msg = chat_pb2.ChatResponse(
                        action_request=chat_pb2.ActionRequest(
                            type=chat_pb2.REQUEST_GPS,
                            request_id=args.get("request_id", session_id),
                            message=self._gps_message(language),
                        )
                    )
                    # This is yielded outside — handle via a queue
                    self._pending_actions[session_id] = action_msg
                    return json.dumps({
                        "status": "waiting",
                        "message": "Waiting for user GPS location..."
                    })

                return await self.tools.execute(name, args)

            async for chunk in self.llm.completion_with_tools(
                messages=messages,
                tools=tool_defs,
                tool_executor=execute_tool,
            ):
                if chunk["type"] == "text":
                    full_response.append(chunk["content"])
                    yield chat_pb2.ChatResponse(
                        text_chunk=chat_pb2.TextChunk(
                            content=chunk["content"],
                            is_final=False,
                        )
                    )

                elif chunk["type"] == "finish":
                    # Send final text marker
                    yield chat_pb2.ChatResponse(
                        text_chunk=chat_pb2.TextChunk(
                            content="",
                            is_final=True,
                        )
                    )

                    # Try to parse an order draft from the response
                    full_text = "".join(full_response)
                    order_draft = self.parser.extract_order_draft(full_text)
                    if order_draft:
                        yield chat_pb2.ChatResponse(
                            order_draft=order_draft,
                        )

                elif chunk["type"] == "error":
                    yield chat_pb2.ChatResponse(
                        error=chat_pb2.ErrorInfo(
                            code="LLM_ERROR",
                            message=chunk["content"],
                        )
                    )

            # Step 6: Save conversation to session
            await self.sessions.append(
                session_id=session_id,
                user_message=processed,
                assistant_message="".join(full_response),
            )

        except Exception as e:
            logger.exception("chat_error", session_id=session_id)
            yield chat_pb2.ChatResponse(
                error=chat_pb2.ErrorInfo(
                    code="INTERNAL_ERROR",
                    message="Something went wrong. Please try again.",
                )
            )

    async def ProvideLocation(self, request, context):
        """
        Called by Go backend when mobile provides GPS coordinates.
        Stores the location in session so the next LLM tool round can use it.
        """
        await self.sessions.set_location(
            session_id=request.session_id,
            request_id=request.request_id,
            location=request.location,
        )
        return chat_pb2.LocationAck(success=True)

    def _gps_message(self, language: str) -> str:
        if language == "ar":
            return "جارٍ تحديد موقعك..."
        return "Fetching your location..."
```

### 5.5 FastAPI app entry point

```python
# app/main.py
import asyncio
import grpc
from concurrent import futures
from contextlib import asynccontextmanager

import structlog
import uvicorn
from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from app.config import settings
from app.api.health import router as health_router
from app.grpc_server.server import serve_grpc

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start gRPC server in background
    grpc_task = asyncio.create_task(serve_grpc())
    logger.info("grpc_started", port=settings.grpc_port)

    yield

    # Shutdown
    grpc_task.cancel()
    logger.info("shutdown_complete")


app = FastAPI(
    title="Yedu AI Service",
    version="1.0.0",
    lifespan=lifespan,
)

# Prometheus metrics
Instrumentator().instrument(app).expose(app)

# Health check routes (used by K8s probes)
app.include_router(health_router)


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.service_host,
        port=settings.service_port,
        reload=settings.env == "development",
    )
```

```python
# app/grpc_server/server.py
import grpc
from app.config import settings
from app.proto import chat_pb2_grpc
from app.grpc_server.chat_servicer import ChatServicer


async def serve_grpc():
    server = grpc.aio.server()
    chat_pb2_grpc.add_ChatServiceServicer_to_server(ChatServicer(), server)
    server.add_insecure_port(f"[::]:{settings.grpc_port}")
    await server.start()
    await server.wait_for_termination()
```

### 5.6 Health check

```python
# app/api/health.py
from fastapi import APIRouter
import redis.asyncio as redis
from app.config import settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    return {"status": "ok", "service": "yedu-ai-service"}


@router.get("/health/ready")
async def readiness():
    """K8s readiness probe — checks Redis connectivity."""
    try:
        r = redis.from_url(settings.redis_url)
        await r.ping()
        return {"status": "ready"}
    except Exception as e:
        return {"status": "not_ready", "error": str(e)}
```

---

## 6. Phase 2 — Multi-modal input processing

### 6.1 Input router

```python
# app/core/router.py
from dataclasses import dataclass
from app.processors.voice import VoiceProcessor
from app.processors.image import ImageProcessor
from app.processors.text import TextProcessor


@dataclass
class ProcessedInput:
    """Unified representation of all input modalities."""
    text: str                              # Original or transcribed text
    transcribed_from_voice: bool = False   # True if text came from STT
    images_base64: list[str] | None = None # Base64 encoded images for vision
    original_text: str = ""                # Raw text before preprocessing


class InputRouter:
    def __init__(self):
        self.voice = VoiceProcessor()
        self.image = ImageProcessor()
        self.text = TextProcessor()

    async def process(
        self,
        text: str = "",
        images: list[bytes] | None = None,
        voice: bytes | None = None,
        voice_mime: str = "",
    ) -> ProcessedInput:
        """
        Process all input modalities into a unified format
        that can be sent to any LLM.
        """
        result_text = text
        transcribed = False

        # 1. Transcribe voice if present
        if voice:
            transcription = await self.voice.transcribe(voice, voice_mime)
            if result_text:
                result_text = f"{result_text}\n\n[Voice message]: {transcription}"
            else:
                result_text = transcription
            transcribed = True

        # 2. Preprocess text
        result_text = self.text.preprocess(result_text)

        # 3. Encode images for vision models
        encoded_images = None
        if images:
            encoded_images = [
                self.image.encode_for_llm(img) for img in images
            ]

        return ProcessedInput(
            text=result_text,
            transcribed_from_voice=transcribed,
            images_base64=encoded_images,
            original_text=text,
        )
```

### 6.2 Voice processor (Whisper)

```python
# app/processors/voice.py
import tempfile
import os
from app.config import settings
import structlog

logger = structlog.get_logger()


class VoiceProcessor:
    """
    Transcribe voice to text using Whisper.
    Supports both local model and OpenAI API.
    """

    def __init__(self):
        self.mode = settings.whisper_mode

        if self.mode == "local":
            import whisper
            self.model = whisper.load_model(settings.whisper_model)
            logger.info("whisper_loaded", model=settings.whisper_model, mode="local")

    async def transcribe(self, audio_bytes: bytes, mime_type: str) -> str:
        """Transcribe audio bytes to text."""
        if self.mode == "api":
            return await self._transcribe_api(audio_bytes, mime_type)
        return self._transcribe_local(audio_bytes, mime_type)

    def _transcribe_local(self, audio_bytes: bytes, mime_type: str) -> str:
        ext = self._mime_to_ext(mime_type)
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as f:
            f.write(audio_bytes)
            f.flush()
            try:
                result = self.model.transcribe(f.name)
                return result["text"].strip()
            finally:
                os.unlink(f.name)

    async def _transcribe_api(self, audio_bytes: bytes, mime_type: str) -> str:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=settings.openai_api_key_whisper)

        ext = self._mime_to_ext(mime_type)
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as f:
            f.write(audio_bytes)
            f.flush()
            try:
                with open(f.name, "rb") as audio_file:
                    result = await client.audio.transcriptions.create(
                        model="whisper-1",
                        file=audio_file,
                        language="en",  # Auto-detect also works
                    )
                return result.text.strip()
            finally:
                os.unlink(f.name)

    @staticmethod
    def _mime_to_ext(mime_type: str) -> str:
        mapping = {
            "audio/m4a": ".m4a",
            "audio/mp4": ".m4a",
            "audio/mpeg": ".mp3",
            "audio/mp3": ".mp3",
            "audio/wav": ".wav",
            "audio/webm": ".webm",
            "audio/ogg": ".ogg",
        }
        return mapping.get(mime_type, ".wav")
```

### 6.3 Image processor

```python
# app/processors/image.py
import base64
import io
from PIL import Image


class ImageProcessor:
    """Encode images for LLM vision APIs."""

    MAX_SIZE = (1024, 1024)  # Max dimensions to keep tokens manageable

    def encode_for_llm(self, image_bytes: bytes) -> str:
        """
        Resize if needed and return base64-encoded JPEG.
        All major LLM providers accept base64 images in the
        OpenAI-compatible format that LiteLLM uses.
        """
        img = Image.open(io.BytesIO(image_bytes))

        # Convert to RGB if necessary (handles PNG with alpha)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")

        # Resize if too large
        img.thumbnail(self.MAX_SIZE, Image.LANCZOS)

        # Encode as JPEG
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=85)
        return base64.b64encode(buffer.getvalue()).decode("utf-8")
```

---

## 7. Phase 3 — Tool calling & location resolution

### 7.1 Tool definitions

```python
# app/models/tools.py

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "search_place",
            "description": (
                "Search for a place or location by name using Google Places API. "
                "Use this when the user mentions a destination or pickup point by name, "
                "like 'Burj Khalifa', 'Dubai Mall', 'the airport', etc. "
                "Returns the place name, formatted address, and GPS coordinates."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The place name or search query, e.g. 'Burj Khalifa Dubai'",
                    },
                    "language": {
                        "type": "string",
                        "enum": ["en", "ar"],
                        "description": "Response language",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "request_user_location",
            "description": (
                "Request the user's current GPS location from their device. "
                "Use this ONLY when the user says 'from my location', 'from here', "
                "'from where I am', 'min makani' (Arabic), or similar phrases indicating "
                "they want to use their current position as pickup or dropoff."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "request_id": {
                        "type": "string",
                        "description": "Unique ID to track this GPS request",
                    },
                    "purpose": {
                        "type": "string",
                        "enum": ["pickup", "dropoff", "waypoint"],
                        "description": "Why we need the location",
                    },
                },
                "required": ["request_id", "purpose"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reverse_geocode",
            "description": (
                "Convert GPS coordinates to a human-readable address. "
                "Use when you have coordinates but need the address for display."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "latitude": {"type": "number"},
                    "longitude": {"type": "number"},
                },
                "required": ["latitude", "longitude"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_order_draft",
            "description": (
                "Create a ride order draft once ALL locations are resolved. "
                "Call this ONLY after you have coordinates for every stop. "
                "The draft will be shown to the user for confirmation — "
                "the order is NOT created until they confirm."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "stops": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "order": {"type": "integer"},
                                "label": {"type": "string"},
                                "latitude": {"type": "number"},
                                "longitude": {"type": "number"},
                                "type": {
                                    "type": "string",
                                    "enum": ["pickup", "waypoint", "dropoff"],
                                },
                            },
                            "required": ["order", "label", "latitude", "longitude", "type"],
                        },
                        "description": "Ordered list of stops: first is pickup, last is dropoff, middle are waypoints.",
                    },
                    "summary": {
                        "type": "string",
                        "description": "Human-readable summary of the route, e.g. 'Dubai Airport → Dubai Mall → Burj Khalifa'",
                    },
                },
                "required": ["stops", "summary"],
            },
        },
    },
]
```

### 7.2 Tool registry & executors

```python
# app/tools/__init__.py
import json
from app.tools.places_search import PlacesSearchTool
from app.tools.geocode import GeocodeTool
from app.tools.device_location import DeviceLocationTool
from app.models.tools import TOOL_DEFINITIONS


class ToolRegistry:
    """Central registry for all available tools."""

    def __init__(self):
        self._executors = {
            "search_place": PlacesSearchTool(),
            "request_user_location": DeviceLocationTool(),
            "reverse_geocode": GeocodeTool(),
            "create_order_draft": self._create_draft,
        }

    def get_definitions(self) -> list[dict]:
        return TOOL_DEFINITIONS

    async def execute(self, name: str, arguments: dict) -> str:
        executor = self._executors.get(name)
        if not executor:
            return json.dumps({"error": f"Unknown tool: {name}"})

        if callable(executor) and not hasattr(executor, 'execute'):
            return await executor(arguments)

        return await executor.execute(arguments)

    async def _create_draft(self, args: dict) -> str:
        """
        The create_order_draft tool doesn't call an external API.
        It just validates and returns the structured data, which the
        response parser will extract from the LLM output.
        """
        return json.dumps({
            "status": "draft_created",
            "stops": args["stops"],
            "summary": args["summary"],
            "message": "Order draft ready. Ask the user to confirm.",
        })
```

### 7.3 Google Places tool

```python
# app/tools/places_search.py
import json
import httpx
import structlog
from app.config import settings

logger = structlog.get_logger()


class PlacesSearchTool:
    """Search for places using Google Places API (New)."""

    BASE_URL = "https://places.googleapis.com/v1/places:searchText"

    async def execute(self, arguments: dict) -> str:
        query = arguments["query"]
        language = arguments.get("language", "en")

        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.BASE_URL,
                json={
                    "textQuery": query,
                    "languageCode": language,
                    "maxResultCount": 3,
                },
                headers={
                    "Content-Type": "application/json",
                    "X-Goog-Api-Key": settings.google_places_api_key,
                    "X-Goog-FieldMask": (
                        "places.displayName,"
                        "places.formattedAddress,"
                        "places.location,"
                        "places.id"
                    ),
                },
            )

        if response.status_code != 200:
            logger.error("places_api_error", status=response.status_code, body=response.text)
            return json.dumps({"error": "Failed to search places"})

        data = response.json()
        places = data.get("places", [])

        results = []
        for place in places:
            loc = place.get("location", {})
            results.append({
                "name": place.get("displayName", {}).get("text", ""),
                "address": place.get("formattedAddress", ""),
                "latitude": loc.get("latitude"),
                "longitude": loc.get("longitude"),
                "place_id": place.get("id", ""),
            })

        return json.dumps({"places": results})
```

### 7.4 Device location tool

```python
# app/tools/device_location.py
import json
import uuid


class DeviceLocationTool:
    """
    This tool doesn't call an API — it signals the gRPC layer
    to send an ActionRequest back to the client, asking for GPS.
    """

    async def execute(self, arguments: dict) -> str:
        request_id = arguments.get("request_id", str(uuid.uuid4()))
        purpose = arguments.get("purpose", "pickup")

        # Return a marker that the chat servicer will interpret
        # as "send ActionRequest to client and wait"
        return json.dumps({
            "action": "REQUEST_GPS",
            "request_id": request_id,
            "purpose": purpose,
            "status": "pending",
            "message": (
                "I've asked for the user's current location. "
                "The GPS coordinates will be provided shortly."
            ),
        })
```

---

## 8. Phase 4 — Token queue & multi-provider setup

### 8.1 LiteLLM Proxy configuration

The LiteLLM Proxy is a **separate process** that manages API keys, load balancing, and rate limiting. Your AI service talks to it instead of directly to providers.

```yaml
# litellm_config/config.yaml

model_list:
  # OpenAI models — multiple keys for rotation
  - model_name: "gpt-4o"
    litellm_params:
      model: "gpt-4o"
      api_key: "sk-key-1-..."
    model_info:
      id: "openai-key-1"
  - model_name: "gpt-4o"
    litellm_params:
      model: "gpt-4o"
      api_key: "sk-key-2-..."
    model_info:
      id: "openai-key-2"
  - model_name: "gpt-4o"
    litellm_params:
      model: "gpt-4o"
      api_key: "sk-key-3-..."
    model_info:
      id: "openai-key-3"

  # Claude models
  - model_name: "claude-sonnet"
    litellm_params:
      model: "claude-sonnet-4-20250514"
      api_key: "sk-ant-key-1-..."
  - model_name: "claude-sonnet"
    litellm_params:
      model: "claude-sonnet-4-20250514"
      api_key: "sk-ant-key-2-..."

  # Gemini models
  - model_name: "gemini-flash"
    litellm_params:
      model: "gemini/gemini-2.0-flash"
      api_key: "AIza-key-1-..."
  - model_name: "gemini-flash"
    litellm_params:
      model: "gemini/gemini-2.0-flash"
      api_key: "AIza-key-2-..."

  # Ollama (self-hosted, no API key needed)
  - model_name: "ollama-llama"
    litellm_params:
      model: "ollama/llama3.1:70b"
      api_base: "http://ollama:11434"

# Load balancing settings
router_settings:
  routing_strategy: "least-busy"    # Options: simple-shuffle, least-busy, latency-based-routing
  num_retries: 3
  retry_after: 5                     # seconds between retries
  timeout: 60                        # seconds
  allowed_fails: 2                   # failures before removing from rotation

  # Fallback chain: if primary model fails, try these in order
  fallbacks:
    - gpt-4o: ["claude-sonnet", "gemini-flash"]
    - claude-sonnet: ["gpt-4o", "gemini-flash"]
    - gemini-flash: ["gpt-4o", "claude-sonnet"]

# Rate limiting per key
litellm_settings:
  max_budget: 100.0               # Max spend in USD per day
  budget_duration: "1d"
  num_retries: 2
  request_timeout: 45
  set_verbose: false

# Enable spend tracking
general_settings:
  master_key: "sk-yedu-proxy-master-..."  # Admin key for proxy management
  database_url: "postgresql://litellm:pass@db:5432/litellm"  # Optional: for persistent tracking
```

### 8.2 Docker Compose

```yaml
# docker/docker-compose.yml
version: "3.9"

services:
  ai-service:
    build:
      context: ..
      dockerfile: docker/Dockerfile
    ports:
      - "8100:8100"   # HTTP (health checks)
      - "50051:50051"  # gRPC
    environment:
      - LITELLM_PROXY_URL=http://litellm-proxy:4000
      - REDIS_URL=redis://redis:6379/0
      - GOOGLE_PLACES_API_KEY=${GOOGLE_PLACES_API_KEY}
      - WHISPER_MODE=local
      - WHISPER_MODEL=base
    depends_on:
      - litellm-proxy
      - redis
    volumes:
      - whisper-cache:/root/.cache/whisper

  litellm-proxy:
    image: ghcr.io/berriai/litellm:main-latest
    ports:
      - "4000:4000"
    volumes:
      - ../litellm_config/config.yaml:/app/config.yaml
    command: >
      --config /app/config.yaml
      --port 4000
      --detailed_debug
    environment:
      - LITELLM_MASTER_KEY=sk-yedu-proxy-master-key

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis-data:/data

  # Optional: local Ollama for development
  ollama:
    image: ollama/ollama:latest
    ports:
      - "11434:11434"
    volumes:
      - ollama-models:/root/.ollama
    profiles:
      - local-llm

volumes:
  redis-data:
  whisper-cache:
  ollama-models:
```

### 8.3 Dockerfile

```dockerfile
# docker/Dockerfile
FROM python:3.11-slim

WORKDIR /app

# System deps for whisper and audio processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Generate proto files
RUN python -m grpc_tools.protoc \
    -I./app/proto \
    --python_out=./app/proto \
    --grpc_python_out=./app/proto \
    ./app/proto/chat.proto

EXPOSE 8100 50051

CMD ["python", "-m", "app.main"]
```

---

## 9. Phase 5 — Order confirmation flow

### 9.1 Prompt builder (system prompt)

```python
# app/core/prompt_builder.py
from app.core.router import ProcessedInput


class PromptBuilder:
    """Build the messages array for the LLM."""

    SYSTEM_PROMPT_EN = """You are Yedu AI, a smart ride booking assistant for the Yedu taxi platform in the UAE.

Your job is to help passengers book rides by understanding their natural language requests.

## Rules

1. ALWAYS use the `search_place` tool to look up any location mentioned by name. Never guess coordinates.
2. If the user says "from my location", "from here", or similar → call `request_user_location` with purpose="pickup".
3. If the user says "to my location" or "drop me here" → call `request_user_location` with purpose="dropoff".
4. The user can specify multiple stops in one message. Parse ALL of them. The first mentioned is pickup, the last is dropoff, everything in between is a waypoint.
5. After resolving ALL locations, call `create_order_draft` with the complete stop list.
6. ALWAYS respond in the same language the user writes in. If they write in Arabic, respond in Arabic.
7. If a place search returns multiple results, ask the user to clarify which one they mean.
8. If information is missing (no pickup or no dropoff), ask for it — don't guess.

## Response format

- Respond in markdown.
- Be concise but friendly.
- When you create an order draft, summarize the route clearly:
  "✅ **Your ride:**\n- 📍 Pickup: [name]\n- 📍 Dropoff: [name]\n\nPlease confirm to book."

## User context

- Name: {user_name}
- Saved addresses: {saved_addresses}
- Last known location: {last_location}
"""

    SYSTEM_PROMPT_AR = """أنت Yedu AI، مساعد ذكي لحجز الرحلات في منصة يدو لسيارات الأجرة في الإمارات.

مهمتك هي مساعدة الركاب في حجز الرحلات من خلال فهم طلباتهم بلغة طبيعية.

## القواعد

1. استخدم دائمًا أداة `search_place` للبحث عن أي موقع مذكور بالاسم. لا تخمن الإحداثيات أبدًا.
2. إذا قال المستخدم "من موقعي" أو "من هنا" → استدعِ `request_user_location` مع purpose="pickup".
3. إذا قال المستخدم "إلى موقعي" أو "أنزلني هنا" → استدعِ `request_user_location` مع purpose="dropoff".
4. يمكن للمستخدم تحديد عدة محطات في رسالة واحدة. حلل جميعها. الأول هو نقطة الالتقاط، والأخير هو الوجهة، وكل ما بينهما هو محطات وسيطة.
5. بعد تحديد جميع المواقع، استدعِ `create_order_draft` مع قائمة المحطات الكاملة.
6. رد دائمًا بنفس اللغة التي يكتب بها المستخدم.
7. إذا أعاد البحث عدة نتائج، اطلب من المستخدم التوضيح.
8. إذا كانت المعلومات ناقصة (بدون نقطة التقاط أو وجهة)، اسأل عنها.

## سياق المستخدم

- الاسم: {user_name}
- العناوين المحفوظة: {saved_addresses}
- آخر موقع معروف: {last_location}
"""

    def build(
        self,
        processed_input: ProcessedInput,
        user_context,
        history: list[dict],
        language: str = "en",
    ) -> list[dict]:
        """Build the full messages array for the LLM."""

        # Choose system prompt based on language
        template = self.SYSTEM_PROMPT_AR if language == "ar" else self.SYSTEM_PROMPT_EN

        # Format saved addresses
        saved = "None"
        if user_context and user_context.saved_addresses:
            saved = ", ".join(
                f"{a.label}: {a.location.address}" for a in user_context.saved_addresses
            )

        # Format last known location
        last_loc = "Unknown"
        if user_context and user_context.last_known_location:
            loc = user_context.last_known_location
            last_loc = f"{loc.latitude}, {loc.longitude}"
            if loc.address:
                last_loc = f"{loc.address} ({last_loc})"

        system_prompt = template.format(
            user_name=user_context.display_name if user_context else "Passenger",
            saved_addresses=saved,
            last_location=last_loc,
        )

        messages = [{"role": "system", "content": system_prompt}]

        # Add conversation history
        messages.extend(history)

        # Build user message (potentially multi-modal)
        user_content = []

        # Add text
        if processed_input.text:
            user_content.append({
                "type": "text",
                "text": processed_input.text,
            })

        # Add images (for vision models)
        if processed_input.images_base64:
            for img_b64 in processed_input.images_base64:
                user_content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{img_b64}",
                    },
                })

            # Add instruction for image analysis
            user_content.append({
                "type": "text",
                "text": (
                    "The user sent image(s) that may show a location, "
                    "address, or place they want to go to or be picked up from. "
                    "Identify the location from the image and use search_place "
                    "to find its coordinates."
                ),
            })

        messages.append({"role": "user", "content": user_content})

        return messages
```

### 9.2 Response parser

```python
# app/core/response_parser.py
import json
import re
import structlog
from app.proto import chat_pb2

logger = structlog.get_logger()


class ResponseParser:
    """Extract structured order data from LLM responses."""

    def extract_order_draft(self, full_response: str) -> chat_pb2.OrderDraft | None:
        """
        Look for a JSON order draft in the LLM's tool call output.
        If found, convert to protobuf OrderDraft.
        """
        # The LLM will have called create_order_draft as a tool,
        # so the draft is already in the tool results.
        # This method handles cases where we need to extract from text.

        # Try to find JSON block in response
        json_match = re.search(r'```json\s*(\{.*?\})\s*```', full_response, re.DOTALL)
        if not json_match:
            return None

        try:
            data = json.loads(json_match.group(1))
            if "stops" not in data:
                return None

            stops = []
            for s in data["stops"]:
                stop = chat_pb2.Stop(
                    order=s["order"],
                    label=s["label"],
                    location=chat_pb2.Location(
                        latitude=s["latitude"],
                        longitude=s["longitude"],
                    ),
                    type=self._stop_type(s.get("type", "waypoint")),
                )
                stops.append(stop)

            return chat_pb2.OrderDraft(
                draft_id=data.get("draft_id", ""),
                stops=stops,
                summary=data.get("summary", ""),
            )

        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("order_parse_failed", error=str(e))
            return None

    @staticmethod
    def _stop_type(t: str) -> int:
        return {
            "pickup": chat_pb2.PICKUP,
            "waypoint": chat_pb2.WAYPOINT,
            "dropoff": chat_pb2.DROPOFF,
        }.get(t, chat_pb2.WAYPOINT)
```

---

## 10. Phase 6 — Production hardening

### 10.1 Session manager (Redis)

```python
# app/session/manager.py
import json
import redis.asyncio as redis
from app.config import settings
from app.core.router import ProcessedInput
import structlog

logger = structlog.get_logger()


class SessionManager:
    """Redis-backed conversation session storage."""

    def __init__(self):
        self.redis = redis.from_url(settings.redis_url, decode_responses=True)
        self.ttl = settings.session_ttl_seconds

    async def get_history(self, session_id: str) -> list[dict]:
        """Retrieve conversation history for a session."""
        key = f"session:{session_id}:history"
        raw = await self.redis.get(key)
        if not raw:
            return []
        return json.loads(raw)

    async def append(
        self, session_id: str, user_message: ProcessedInput, assistant_message: str
    ):
        """Append a turn to the conversation history."""
        key = f"session:{session_id}:history"
        history = await self.get_history(session_id)

        # Add user turn
        history.append({
            "role": "user",
            "content": user_message.text,
        })

        # Add assistant turn
        history.append({
            "role": "assistant",
            "content": assistant_message,
        })

        # Keep only last 20 messages to manage context window
        if len(history) > 20:
            history = history[-20:]

        await self.redis.setex(key, self.ttl, json.dumps(history))

    async def set_location(self, session_id: str, request_id: str, location):
        """Store a GPS location received from the client."""
        key = f"session:{session_id}:location:{request_id}"
        data = json.dumps({
            "latitude": location.latitude,
            "longitude": location.longitude,
            "address": location.address,
        })
        await self.redis.setex(key, 300, data)  # 5 min TTL

    async def get_location(self, session_id: str, request_id: str) -> dict | None:
        """Retrieve a stored GPS location."""
        key = f"session:{session_id}:location:{request_id}"
        raw = await self.redis.get(key)
        if raw:
            return json.loads(raw)
        return None
```

### 10.2 Logging configuration

```python
# In app/main.py, before creating the FastAPI app:

import structlog

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer()
        if settings.env == "development"
        else structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(
        getattr(structlog, settings.log_level.upper(), structlog.INFO)
    ),
)
```

### 10.3 Testing

```python
# tests/conftest.py
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def mock_llm_client():
    client = AsyncMock()

    async def fake_stream(*args, **kwargs):
        yield {"type": "text", "content": "I'll book a ride for you. "}
        yield {"type": "text", "content": "Looking up Burj Khalifa..."}
        yield {"type": "tool_call", "id": "tc_1", "name": "search_place", "arguments": '{"query": "Burj Khalifa"}'}
        yield {"type": "finish", "reason": "tool_calls"}

    client.stream_completion = fake_stream
    return client


@pytest.fixture
def mock_places_tool():
    tool = AsyncMock()
    tool.execute.return_value = '{"places": [{"name": "Burj Khalifa", "latitude": 25.1972, "longitude": 55.2744, "address": "1 Sheikh Mohammed bin Rashid Blvd"}]}'
    return tool
```

```python
# tests/test_router.py
import pytest
from app.core.router import InputRouter


@pytest.mark.asyncio
async def test_text_only():
    router = InputRouter()
    result = await router.process(text="Take me to Dubai Mall")
    assert result.text == "Take me to Dubai Mall"
    assert result.images_base64 is None
    assert result.transcribed_from_voice is False


@pytest.mark.asyncio
async def test_mixed_input():
    router = InputRouter()
    fake_image = b'\xff\xd8\xff\xe0' + b'\x00' * 100  # Minimal JPEG header
    result = await router.process(
        text="Go here",
        images=[fake_image],
    )
    assert result.text == "Go here"
    assert result.images_base64 is not None
    assert len(result.images_base64) == 1
```

---

## 11. API reference

### gRPC endpoints

| Method | Request | Response | Description |
|---|---|---|---|
| `Chat` | `ChatRequest` | `stream ChatResponse` | Main chat endpoint. Accepts multi-modal input, streams markdown + order draft. |
| `ProvideLocation` | `LocationUpdate` | `LocationAck` | Callback for GPS location from mobile client. |

### HTTP endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness probe |
| `GET` | `/health/ready` | Readiness probe (checks Redis) |
| `GET` | `/metrics` | Prometheus metrics |

### ChatResponse payload types

| Type | When sent | Content |
|---|---|---|
| `text_chunk` | During streaming | Partial markdown text. `is_final=true` marks the end. |
| `order_draft` | After text stream ends | Structured order with resolved stops. Only sent if LLM produced a complete order. |
| `action_request` | During tool execution | Tells client to perform an action (e.g., provide GPS). Type: `REQUEST_GPS`. |
| `error` | On failure | Error code and human-readable message. |

---

## 12. Configuration reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `SERVICE_HOST` | No | `0.0.0.0` | HTTP bind host |
| `SERVICE_PORT` | No | `8100` | HTTP port |
| `GRPC_PORT` | No | `50051` | gRPC port |
| `ENV` | No | `development` | Environment (development/staging/production) |
| `LOG_LEVEL` | No | `info` | Logging level |
| `REDIS_URL` | Yes | — | Redis connection URL |
| `LITELLM_PROXY_URL` | No* | — | LiteLLM Proxy URL. If not set, calls providers directly. |
| `OPENAI_API_KEY` | No* | — | OpenAI API key (direct mode) |
| `ANTHROPIC_API_KEY` | No* | — | Anthropic API key (direct mode) |
| `GEMINI_API_KEY` | No* | — | Google Gemini API key (direct mode) |
| `GOOGLE_PLACES_API_KEY` | Yes | — | Google Places API key |
| `WHISPER_MODEL` | No | `base` | Whisper model size |
| `WHISPER_MODE` | No | `local` | `local` or `api` |
| `SESSION_TTL_SECONDS` | No | `1800` | Session expiry (seconds) |
| `DEFAULT_MODEL` | No | `gpt-4o` | Default LLM model |

*Either set `LITELLM_PROXY_URL` or individual API keys.

---

## 13. What to ask from the Go backend developer

Before writing any code, schedule a meeting with the Go backend developer and get answers to these questions. **Do not proceed without alignment on items marked 🔴.**

### 🔴 Critical (blockers)

1. **Proto file agreement** — "Can we review and finalize `chat.proto` together? I need you to generate Go code from the same proto file. Which repo will the shared proto live in?"

2. **Authentication flow** — "How will you authenticate the user before forwarding to the AI service? I need the `user_id` and `session_id` in every gRPC request. Will you pass the JWT or already-validated user info?"

3. **gRPC client implementation** — "Can you implement a gRPC client in Go that: (a) forwards the mobile request to my service, (b) streams my response chunks back to the mobile via SSE, (c) forwards `ProvideLocation` when mobile sends GPS?"

4. **New REST endpoint** — "I need you to create `/api/v1/ai/chat` in the Go backend that accepts multipart form data from mobile (text + images + voice files) and proxies it to my gRPC service."

5. **User context data** — "The proto `UserContext` message includes saved addresses and last known location. Can you populate this from your database when forwarding the request?"

6. **Order creation endpoint** — "After the user confirms an order draft, mobile will call your existing order creation endpoint. What is the exact payload format? I need to make sure my `OrderDraft` maps cleanly to your `CreateOrder` request."

### 🟡 Important (needed soon)

7. **SSE streaming format** — "How will you stream my response to mobile? I suggest SSE with these event types: `text` (markdown chunks), `order_draft` (JSON), `action` (GPS request), `error`. Can you agree on this?"

8. **GPS callback flow** — "When I send an `ActionRequest` of type `REQUEST_GPS`, the flow is: your Go backend → mobile (trigger GPS) → mobile sends GPS → your Go backend → my `ProvideLocation` gRPC method. Can you implement this round-trip?"

9. **Rate limiting** — "Will you rate-limit AI chat requests at the Go backend level? I suggest max 10 requests per minute per user. This protects my LLM token budget."

10. **Error codes** — "Let's agree on error codes. I'll send: `LLM_ERROR`, `TOOL_ERROR`, `INTERNAL_ERROR`, `SESSION_EXPIRED`. What error format does your API return to mobile?"

### 🟢 Nice to have

11. **Monitoring** — "I expose Prometheus metrics at `/metrics`. Can you add my service to your Grafana dashboards?"

12. **Deployment** — "How are services deployed? Docker Compose, K8s, or something else? I'll provide a Dockerfile."

13. **Environments** — "What are the staging/production URLs and how do I get access to deploy?"

---

## 14. What to ask from the mobile (KMP) developer

### 🔴 Critical (blockers)

1. **Multipart request format** — "The AI chat endpoint accepts multipart/form-data with these fields: `text` (string), `images` (file[], JPEG/PNG), `voice` (file, m4a/wav/mp3), `language` (string, 'en' or 'ar'), `session_id` (string, UUID). Can you send all of these in a single request?"

2. **SSE client** — "The response comes back as Server-Sent Events. You'll receive these event types:
   - `text` → markdown chunk (append to chat bubble, render as markdown)
   - `order_draft` → JSON with stops array (render as a confirmation card with map)
   - `action:request_gps` → trigger device GPS, then POST the coordinates back to `/api/v1/ai/location`
   - `error` → show error message  
   Can you implement an SSE client that handles all four types?"

3. **GPS callback** — "When you receive an `action:request_gps` event, you need to: (a) get the device's current GPS, (b) POST it to `/api/v1/ai/location` with `session_id` and `request_id` from the event, (c) show a loading indicator like 'Fetching your location...' while this happens. The AI service will continue the response once it has the coordinates."

4. **Order confirmation UI** — "When you receive an `order_draft` event, render a card showing: pickup name + pin, dropoff name + pin, any waypoints, and a 'Confirm' button. The map should show all stops. When the user taps 'Confirm', call the Go backend's existing order creation endpoint with the draft data."

5. **Session management** — "Generate a UUID `session_id` when the user opens the AI chat screen. Keep the same session_id for the entire conversation. Generate a new one if they close and reopen the chat."

6. **Voice recording format** — "Please send voice as m4a or wav. Include the MIME type in the multipart field. What format does your recorder output?"

### 🟡 Important

7. **Image handling** — "Compress images to max 1024x1024 before sending. This keeps tokens manageable. What's the max number of images you'll allow per message? I suggest 3."

8. **Markdown rendering** — "The AI response is streamed as markdown. You'll need a markdown renderer that updates in real time as chunks arrive. It will include bold, bullet points, and emoji (✅, 📍). Do you have a KMP markdown library in mind?"

9. **Loading states** — "Show a typing indicator while receiving SSE chunks. Show 'Fetching your location...' during GPS callback. Show 'Searching for location...' when the AI is calling Places API (I'll send a text chunk for this)."

10. **Dark mode & RTL** — "The AI responds in the same language as the user. For Arabic responses, the chat bubble should be RTL. Please handle this based on the `language` field."

### 🟢 Nice to have

11. **Chat history UI** — "I maintain conversation context for 30 minutes. If the user returns within that window, they can continue the conversation. Can you restore the chat history from the SSE stream?"

12. **Retry on failure** — "If the SSE connection drops, retry with the same `session_id`. I'll reconstruct context from Redis."

---

## 15. Connecting all three services together

This section summarizes how the Mobile app, Go backend, and Python AI service connect.

### Data flow for a single chat message

```
1. USER types: "Take me from my location to Burj Khalifa"

2. MOBILE (KMP)
   ├── Generates session_id (UUID) if new conversation
   ├── Packs: { text, images[], voice, language, session_id }
   └── POST multipart → Go backend: /api/v1/ai/chat

3. GO BACKEND
   ├── Authenticates user (JWT)
   ├── Loads user context (saved addresses, last GPS)
   ├── Opens gRPC stream → Python AI service: ChatService.Chat
   ├── Sends ChatRequest { session_id, user_id, text, images, user_context }
   └── Starts forwarding gRPC stream chunks → SSE to mobile

4. PYTHON AI SERVICE
   ├── Processes input (text, transcribe voice, encode images)
   ├── Builds LLM messages with system prompt + history
   ├── Calls LLM via LiteLLM (streaming)
   │
   ├── LLM calls tool: request_user_location (for "my location")
   │   ├── AI service sends ActionRequest via gRPC stream
   │   ├── Go backend sends SSE event: action:request_gps
   │   ├── Mobile gets GPS → POST /api/v1/ai/location
   │   ├── Go backend calls AI service: ProvideLocation gRPC
   │   └── AI service continues LLM with resolved coordinates
   │
   ├── LLM calls tool: search_place (for "Burj Khalifa")
   │   ├── AI service calls Google Places API
   │   └── Returns coordinates to LLM
   │
   ├── LLM calls tool: create_order_draft
   │   └── AI service returns structured draft
   │
   ├── Streams text chunks via gRPC → Go → SSE → Mobile
   └── Sends OrderDraft via gRPC → Go → SSE → Mobile

5. MOBILE (KMP)
   ├── Renders markdown text in chat bubble (streaming)
   ├── Receives order_draft → shows confirmation card with map
   └── User taps "Confirm" → POST to Go backend: /api/v1/orders (existing)

6. GO BACKEND
   └── Creates the order in the database, dispatches driver
```

### Network topology

```
┌──────────┐     HTTPS/SSE      ┌──────────────┐     gRPC       ┌─────────────┐
│  Mobile   │ ◄───────────────► │  Go Backend   │ ◄────────────► │  AI Service  │
│  (KMP)    │   port 443        │  (existing)   │   port 50051   │  (Python)    │
└──────────┘                    │  port 8080    │               └──────┬──────┘
                                └──────────────┘                       │
                                                              port 4000│
                                                              ┌────────▼───────┐
                                                              │ LiteLLM Proxy  │
                                                              │ (key rotation) │
                                                              └───┬───┬───┬────┘
                                                                  │   │   │
                                                         ┌────────┘   │   └────────┐
                                                         ▼            ▼            ▼
                                                      OpenAI      Claude       Gemini
```

### Minimum viable integration test

To verify the full chain works end-to-end before going to production:

**Step 1** — Start the AI service: `docker-compose up ai-service litellm-proxy redis`

**Step 2** — Test gRPC directly using `grpcurl`:
```bash
grpcurl -plaintext -d '{
  "session_id": "test-001",
  "user_id": "user-001",
  "language": "en",
  "text": "Take me from Dubai Airport to Burj Khalifa"
}' localhost:50051 yedu.ai.v1.ChatService/Chat
```

**Step 3** — Verify you receive streamed `TextChunk` messages followed by an `OrderDraft`.

**Step 4** — Go developer adds gRPC client call inside `/api/v1/ai/chat`, forwarding SSE to mobile.

**Step 5** — Mobile developer points the chat screen to the new endpoint and verifies SSE rendering.

**Step 6** — Test the GPS callback by sending "from my location" and verifying the round-trip.

---

*End of document. For questions, contact the AI service team.*
