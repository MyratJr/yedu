"""
app/grpc_server/server.py

Bootstraps the async gRPC server and binds the ChatServicer.
Called from app/main.py alongside uvicorn.
"""

from __future__ import annotations

import logging

import grpc
import grpc.aio

from app.core.config import get_settings
from app.grpc_server.chat_servicer import ChatServicer
from app.proto import chat_pb2_grpc  # type: ignore[import]

logger = logging.getLogger(__name__)


async def serve() -> None:
    settings = get_settings()
    server = grpc.aio.server()

    chat_pb2_grpc.add_ChatServiceServicer_to_server(ChatServicer(), server)

    listen_addr = f"[::]:{settings.grpc_port}"
    server.add_insecure_port(listen_addr)

    logger.info("gRPC server starting on %s", listen_addr)
    await server.start()
    await server.wait_for_termination()