"""
app/core/response_parser.py

Parses LLM text output → OrderDraft Pydantic model.
Looks for <order_draft>...</order_draft> tags in the response.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from app.models.order import Location, OrderDraft, Stop

logger = logging.getLogger(__name__)

_ORDER_DRAFT_RE = re.compile(
    r"<order_draft>\s*(\{.*?\})\s*</order_draft>", re.DOTALL
)


def extract_order_draft(text: str) -> Optional[OrderDraft]:
    """
    Scans LLM output for an <order_draft>{...}</order_draft> block.
    Returns an OrderDraft if found and valid, otherwise None.
    """
    match = _ORDER_DRAFT_RE.search(text)
    if not match:
        return None

    try:
        raw = json.loads(match.group(1))

        pickup_raw = raw.get("pickup", {})
        dest_raw   = raw.get("destination", {})

        pickup = Location(
            address=pickup_raw.get("address", ""),
            latitude=float(pickup_raw.get("latitude", 0.0)),
            longitude=float(pickup_raw.get("longitude", 0.0)),
        )
        destination = Location(
            address=dest_raw.get("address", ""),
            latitude=float(dest_raw.get("latitude", 0.0)),
            longitude=float(dest_raw.get("longitude", 0.0)),
        )
        stops = [
            Stop(
                address=s.get("address", ""),
                latitude=float(s.get("latitude", 0.0)),
                longitude=float(s.get("longitude", 0.0)),
            )
            for s in raw.get("stops", [])
        ]

        draft = OrderDraft(
            pickup=pickup,
            destination=destination,
            stops=stops,
            ride_type=raw.get("ride_type", "standard"),
            notes=raw.get("notes"),
        )
        logger.debug("Parsed order draft: %s", draft)
        return draft

    except Exception as exc:
        logger.warning("Failed to parse order draft: %s", exc)
        return None


def strip_order_draft_tag(text: str) -> str:
    """Remove the <order_draft> block from text before streaming to the user."""
    return _ORDER_DRAFT_RE.sub("", text).strip()