from __future__ import annotations

import json
import logging
from typing import Optional

import redis.asyncio as aioredis

from app.core.config import get_settings

logger = logging.getLogger(__name__)

MAX_HISTORY = 20
LOCATION_TTL = 300


class SessionManager:
    def __init__(self) -> None:
        settings = get_settings()
        self._redis: aioredis.Redis = aioredis.from_url(
            settings.redis_url, decode_responses=True
        )
        self._ttl = settings.session_ttl_seconds


    def _history_key(self, session_id: str) -> str:
        return f"session:{session_id}:history"

    async def get_history(self, session_id: str) -> list[dict]:
        raw = await self._redis.lrange(self._history_key(session_id), 0, -1)
        return [json.loads(m) for m in raw]

    async def append_message(self, session_id: str, role: str, content: str) -> None:
        key = self._history_key(session_id)
        message = json.dumps({"role": role, "content": content})
        pipe = self._redis.pipeline()
        pipe.rpush(key, message)
        pipe.ltrim(key, -MAX_HISTORY, -1)
        pipe.expire(key, self._ttl)
        await pipe.execute()
        logger.debug("Session %s: appended %s message", session_id, role)

    async def clear(self, session_id: str) -> None:
        await self._redis.delete(self._history_key(session_id))


    def _location_key(self, session_id: str) -> str:
        return f"session:{session_id}:location"

    async def set_location(
        self, session_id: str, latitude: float, longitude: float
    ) -> None:
        key = self._location_key(session_id)
        await self._redis.set(
            key,
            json.dumps({"latitude": latitude, "longitude": longitude}),
            ex=LOCATION_TTL,
        )

    async def get_location(self, session_id: str) -> Optional[dict[str, float]]:
        raw = await self._redis.get(self._location_key(session_id))
        return json.loads(raw) if raw else None


    async def close(self) -> None:
        await self._redis.aclose()


session_manager = SessionManager()