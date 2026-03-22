"""app/tools/places_search.py — Google Places API lookup."""

from __future__ import annotations

import logging
from typing import Optional

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

PLACES_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"



async def search_places(query: str, language: str = "en") -> list[dict]:
    """
    Search Google Places and return a list of results:
    [{"name": ..., "address": ..., "latitude": ..., "longitude": ...}, ...]
    """
    settings = get_settings()
    if not settings.google_places_api_key:
        logger.warning("GOOGLE_PLACES_API_KEY not set — returning empty results")
        return []

    params = {
        "query": query,
        "key": settings.google_places_api_key,
        "language": language,
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(PLACES_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

    results = []
    for place in data.get("results", [])[:3]:
        loc = place.get("geometry", {}).get("location", {})
        results.append(
            {
                "name": place.get("name", ""),
                "address": place.get("formatted_address", ""),
                "latitude": loc.get("lat", 0.0),
                "longitude": loc.get("lng", 0.0),
            }
        )
    logger.debug("Places search '%s' → %d results", query, len(results))
    return results