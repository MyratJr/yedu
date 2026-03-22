from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest.fixture(autouse=True)
def mock_redis():
    redis = MagicMock()
    redis.lrange  = AsyncMock(return_value=[])
    redis.set     = AsyncMock()
    redis.get     = AsyncMock(return_value=None)
    redis.delete  = AsyncMock()
    redis.ping    = AsyncMock(return_value=True)
    redis.aclose  = AsyncMock()

    pipe = MagicMock()
    pipe.rpush   = MagicMock()
    pipe.ltrim   = MagicMock()
    pipe.expire  = MagicMock()
    pipe.execute = AsyncMock()
    redis.pipeline.return_value = pipe

    with patch("app.session.manager.aioredis.from_url", return_value=redis), \
         patch("app.session.manager.session_manager._redis", redis):
        yield redis


@pytest_asyncio.fixture
async def client(mock_redis):
    from app.main import app
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c