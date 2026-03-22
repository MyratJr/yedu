"""
app/tools/device_location.py

Emits an ActionRequest(REQUEST_GPS) message back to the gRPC stream
so the mobile client knows to send its GPS coordinates.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def request_user_location() -> dict:
    """
    Returns an action payload that the stream_handler will forward to the client.
    The actual GPS value arrives via ProvideLocation RPC and is stored in Redis.
    """
    logger.debug("Requesting GPS from client")
    return {"action_type": "REQUEST_GPS", "payload": ""}