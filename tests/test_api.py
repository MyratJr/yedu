"""tests/test_api.py — HTTP health + debug endpoint tests."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health(client: AsyncClient):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_ready(client: AsyncClient):
    resp = await client.get("/ready")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert "redis" in data


@pytest.mark.asyncio
async def test_debug_session_empty(client: AsyncClient):
    resp = await client.get("/debug/session/test-123")
    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"] == "test-123"
    assert data["history"] == []


@pytest.mark.asyncio
async def test_clear_session(client: AsyncClient):
    resp = await client.delete("/debug/session/test-123")
    assert resp.status_code == 200
    assert resp.json()["cleared"] == "test-123"