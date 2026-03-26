"""
app/main.py

FastAPI entry point.
Starts both the HTTP server (uvicorn) and the gRPC server
in the same process using asyncio via the FastAPI lifespan.

Run:
    uvicorn app.main:app --host 0.0.0.0 --port 8100 --reload
"""
from __future__ import annotations
import warnings
warnings.filterwarnings("ignore", category=RuntimeWarning, message="coroutine.*was never awaited")


import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

import grpc.aio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router as api_router
from app.core.config import get_settings
from app.grpc_server.chat_servicer import ChatServicer
from app.proto import chat_pb2_grpc  # type: ignore[import]
from app.session.manager import session_manager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)

settings = get_settings()

# Keep a reference so we can shut it down cleanly
_grpc_server: grpc.aio.Server | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global _grpc_server

    # --- Startup ---
    _grpc_server = grpc.aio.server()
    chat_pb2_grpc.add_ChatServiceServicer_to_server(ChatServicer(), _grpc_server)
    listen_addr = f"[::]:{settings.grpc_port}"
    _grpc_server.add_insecure_port(listen_addr)
    await _grpc_server.start()
    logger.info("gRPC server listening on %s", listen_addr)

    yield

    # --- Shutdown ---
    if _grpc_server:
        await _grpc_server.stop(grace=3)   # 3 s grace period
        logger.info("gRPC server stopped")

    try:
        await session_manager.close()
    except Exception:
        pass

    logger.info("Shutdown complete")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Yedu AI Service",
        description=(
            "Natural-language ride booking. "
            "Accepts text / voice / image input via gRPC, "
            "streams back structured ride orders."
        ),
        version="1.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if not settings.is_production else [],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router)

    return app


app = create_app()