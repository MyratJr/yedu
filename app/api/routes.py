"""
app/api/routes.py

HTTP endpoints: liveness/readiness probes + session management API.
"""

from __future__ import annotations

import json
from typing import List, Optional

import redis.asyncio as aioredis
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from app.core.config import get_settings
from app.session.manager import session_manager

router = APIRouter()


# ── Health ────────────────────────────────────────────────────────────────────

@router.get("/health", tags=["ops"], summary="Liveness check")
async def health():
    return {"status": "ok"}


@router.get("/ready", tags=["ops"], summary="Readiness check — verifies Redis")
async def ready():
    settings = get_settings()
    try:
        r = aioredis.from_url(settings.redis_url)
        await r.ping()
        await r.aclose()
        redis_ok = True
    except Exception:
        redis_ok = False

    return {
        "status": "ok" if redis_ok else "degraded",
        "redis": "ok" if redis_ok else "unreachable",
        "grpc_port": settings.grpc_port,
    }


# ── Chat SSE ──────────────────────────────────────────────────────────────────

@router.post("/chat", tags=["chat"], summary="Chat — streams SSE events (mirrors gRPC Chat RPC)")
async def chat_sse(
    session_id: str = Form(...),
    user_id: str = Form(...),
    language: str = Form("en"),
    text: Optional[str] = Form(None),
    audios: List[UploadFile] = File(default=[]),
    images: List[UploadFile] = File(default=[]),
    favorite_places: List[str] = Form(default=[]),
):
    from app.core.router import handle
    from app.models.chat import ChatRequest

    req = ChatRequest(
        session_id=session_id,
        user_id=user_id,
        language=language,
        text=text or None,
        audios=[await f.read() for f in audios],
        images=[await f.read() for f in images],
        favorite_places=favorite_places,
    )

    async def event_stream():
        async for response in handle(req):
            if response.HasField("text_chunk"):
                data = {
                    "type": "text",
                    "text": response.text_chunk.text,
                    "is_final": response.text_chunk.is_final,
                }
            elif response.HasField("error"):
                data = {
                    "type": "error",
                    "code": response.error.code,
                    "message": response.error.message,
                }
            else:
                continue
            yield f"data: {json.dumps(data)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ── Session API ───────────────────────────────────────────────────────────────

@router.get("/sessions", tags=["sessions"], summary="List all active sessions")
async def list_sessions():
    """Return the IDs of all sessions that have history in Redis."""
    ids = await session_manager.list_sessions()
    return {"sessions": ids, "count": len(ids)}


@router.get("/sessions/{session_id}", tags=["sessions"], summary="Get session history")
async def get_session(session_id: str):
    """Return the full conversation history for a session."""
    history = await session_manager.get_history(session_id)
    if not history:
        raise HTTPException(status_code=404, detail="Session not found or empty")
    return {"session_id": session_id, "messages": history, "count": len(history)}


@router.delete("/sessions/{session_id}", tags=["sessions"], summary="Clear session history")
async def delete_session(session_id: str):
    """Delete all history for a session."""
    history = await session_manager.get_history(session_id)
    if not history:
        raise HTTPException(status_code=404, detail="Session not found or empty")
    await session_manager.clear(session_id)
    return {"cleared": session_id}
