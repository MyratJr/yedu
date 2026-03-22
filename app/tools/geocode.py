"""app/tools/geocode.py — Forward and reverse geocoding via Google Maps."""

from __future__ import annotations

import logging
from typing import Optional

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

GEOCODE_URL  = "https://maps.googleapis.com/maps/api/geocode/json"


async def geocode_address(address: str) -> Optional[dict]:
    """Address → {latitude, longitude, formatted_address}"""
    settings = get_settings()
    params = {"address": address, "key": settings.google_places_api_key}
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(GEOCODE_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

    results = data.get("results", [])
    if not results:
        return None
    loc = results[0]["geometry"]["location"]
    return {
        "formatted_address": results[0]["formatted_address"],
        "latitude":  loc["lat"],
        "longitude": loc["lng"],
    }


async def reverse_geocode(latitude: float, longitude: float) -> Optional[str]:
    """(lat, lng) → human-readable address string."""
    settings = get_settings()
    params = {
        "latlng": f"{latitude},{longitude}",
        "key": settings.google_places_api_key,
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(GEOCODE_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

    results = data.get("results", [])
    if not results:
        return None
    return results[0].get("formatted_address")