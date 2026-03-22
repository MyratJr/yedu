"""
app/api/routes.py

HTTP health and debug endpoints.
These are useful for liveness probes and local development.
"""

from __future__ import annotations

import redis.asyncio as aioredis
from fastapi import APIRouter

from app.core.config import get_settings
from app.session.manager import session_manager

router = APIRouter(tags=["ops"])


@router.get("/health", summary="Liveness check")
async def health():
    return {"status": "ok"}


@router.get("/ready", summary="Readiness check — verifies Redis")
async def ready():
    settings = get_settings()
    try:
        r = aioredis.from_url(settings.redis_url)
        await r.ping()
        await r.aclose()
        redis_ok = True
    except Exception:
        redis_ok = False

    status = "ok" if redis_ok else "degraded"
    return {
        "status": status,
        "redis": "ok" if redis_ok else "unreachable",
        "grpc_port": settings.grpc_port,
    }


@router.get("/debug/session/{session_id}", summary="Inspect session history")
async def debug_session(session_id: str):
    history  = await session_manager.get_history(session_id)
    location = await session_manager.get_location(session_id)
    return {"session_id": session_id, "history": history, "location": location}


@router.delete("/debug/session/{session_id}", summary="Clear session history")
async def clear_session(session_id: str):
    await session_manager.clear(session_id)
    return {"cleared": session_id}