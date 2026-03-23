from __future__ import annotations

import json
import logging

import redis.asyncio as aioredis

from app.core.config import get_settings

logger = logging.getLogger(__name__)

MAX_HISTORY = 20  # max messages kept per session


class SessionManager:
    """Redis-backed conversation history store."""

    def __init__(self) -> None:
        settings = get_settings()
        self._redis: aioredis.Redis = aioredis.from_url(
            settings.redis_url, decode_responses=True
        )
        self._ttl = settings.session_ttl_seconds

    # ── key helpers ──────────────────────────────────────────────────────────

    def _key(self, session_id: str) -> str:
        return f"session:{session_id}:history"

    # ── public API ───────────────────────────────────────────────────────────

    async def get_history(self, session_id: str) -> list[dict]:
        """Return all stored messages for this session (oldest first)."""
        raw = await self._redis.lrange(self._key(session_id), 0, -1)
        return [json.loads(m) for m in raw]

    async def append_message(self, session_id: str, role: str, content: str) -> None:
        """Append one message and keep the list trimmed to MAX_HISTORY."""
        key = self._key(session_id)
        message = json.dumps({"role": role, "content": content})
        pipe = self._redis.pipeline()
        pipe.rpush(key, message)
        pipe.ltrim(key, -MAX_HISTORY, -1)
        pipe.expire(key, self._ttl)
        await pipe.execute()
        logger.debug("session=%s appended role=%s", session_id, role)

    async def list_sessions(self) -> list[str]:
        """Return all active session IDs (scans Redis keys)."""
        keys = []
        async for key in self._redis.scan_iter("session:*:history"):
            # key format: session:{session_id}:history
            parts = key.split(":")
            if len(parts) == 3:
                keys.append(parts[1])
        return keys

    async def clear(self, session_id: str) -> None:
        """Delete all history for this session."""
        await self._redis.delete(self._key(session_id))

    async def close(self) -> None:
        """Close the underlying Redis connection."""
        await self._redis.aclose()


session_manager = SessionManager()
