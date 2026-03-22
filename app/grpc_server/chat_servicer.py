"""
app/grpc_server/chat_servicer.py

Implements the two RPCs defined in chat.proto:
  - Chat()            bidirectional streaming
  - ProvideLocation() unary — stores GPS in Redis
"""

from __future__ import annotations

import logging

import grpc

from app.core import router
from app.models.chat import ChatRequest
from app.proto import chat_pb2, chat_pb2_grpc
from app.session.manager import session_manager

logger = logging.getLogger(__name__)


class ChatServicer(chat_pb2_grpc.ChatServiceServicer):

    async def Chat(self, request_iterator, context: grpc.aio.ServicerContext):
        """
        Bidirectional streaming RPC.
        Reads ChatRequest messages from the client stream and
        yields ChatResponse messages back.
        """
        async for proto_req in request_iterator:
            request = ChatRequest(
                session_id=proto_req.session_id,
                user_id=proto_req.user_id,
                text=proto_req.text_input or None,
                audio=proto_req.audio_input or None,
                image=proto_req.image_input or None,
                language=proto_req.language or "en",
            )

            logger.info(
                "Chat RPC: session=%s user=%s text=%s audio=%s image=%s",
                request.session_id,
                request.user_id,
                bool(request.text),
                bool(request.audio),
                bool(request.image),
            )

            try:
                async for response in router.handle(request):
                    yield response
            except Exception as exc:
                logger.error("Chat handler error: %s", exc)
                yield chat_pb2.ChatResponse(
                    error=chat_pb2.ErrorInfo(
                        code="INTERNAL_ERROR",
                        message=str(exc),
                    )
                )

    async def ProvideLocation(
        self,
        request: chat_pb2.LocationPayload,
        context: grpc.aio.ServicerContext,
    ) -> chat_pb2.LocationAck:
        """
        Unary RPC — client sends GPS coordinates after REQUEST_GPS action.
        Stores them in Redis against the session.
        """
        try:
            await session_manager.set_location(
                session_id=request.session_id,
                latitude=request.latitude,
                longitude=request.longitude,
            )
            logger.info(
                "Location stored: session=%s lat=%.5f lng=%.5f",
                request.session_id,
                request.latitude,
                request.longitude,
            )
            return chat_pb2.LocationAck(success=True)
        except Exception as exc:
            logger.error("ProvideLocation failed: %s", exc)
            return chat_pb2.LocationAck(success=False)