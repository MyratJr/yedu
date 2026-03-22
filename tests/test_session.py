"""tests/test_session.py — session manager unit tests."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.session.manager import SessionManager


@pytest.fixture
def manager():
    with patch("app.session.manager.aioredis.from_url") as mock_fn:
        redis = MagicMock()                      # ← MagicMock, not AsyncMock
        redis.lrange = AsyncMock(return_value=[
            json.dumps({"role": "user", "content": "hello"}),
            json.dumps({"role": "assistant", "content": "hi"}),
        ])
        redis.set  = AsyncMock()
        redis.get  = AsyncMock()
        redis.delete = AsyncMock()

        pipe = MagicMock()                       # ← pipeline is also MagicMock
        pipe.rpush  = MagicMock()
        pipe.ltrim  = MagicMock()
        pipe.expire = MagicMock()
        pipe.execute = AsyncMock()
        redis.pipeline.return_value = pipe       # ← pipeline() returns pipe sync

        mock_fn.return_value = redis
        yield SessionManager(), redis


@pytest.mark.asyncio
async def test_get_history(manager):
    sm, _ = manager
    history = await sm.get_history("sess-1")
    assert len(history) == 2
    assert history[0]["role"] == "user"


@pytest.mark.asyncio
async def test_append_message(manager):
    sm, redis = manager
    pipe = redis.pipeline.return_value
    await sm.append_message("sess-1", "user", "I need a ride")
    pipe.rpush.assert_called_once()
    pipe.ltrim.assert_called_once()
    pipe.expire.assert_called_once()
    pipe.execute.assert_called_once()


@pytest.mark.asyncio
async def test_set_and_get_location(manager):
    sm, redis = manager
    await sm.set_location("sess-1", 37.9868, 58.3610)
    redis.set.assert_called_once()

    redis.get.return_value = json.dumps({"latitude": 37.9868, "longitude": 58.3610})
    loc = await sm.get_location("sess-1")
    assert loc["latitude"] == pytest.approx(37.9868)