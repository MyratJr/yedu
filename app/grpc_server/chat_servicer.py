"""
app/grpc_server/chat_servicer.py

Implements the two RPCs defined in chat.proto:
  - Chat()            bidirectional streaming
"""

from __future__ import annotations

import logging

import grpc

from app.core import router
from app.models.chat import ChatRequest
from app.proto import chat_pb2, chat_pb2_grpc

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
                audios=list(proto_req.audio_inputs),
                images=list(proto_req.image_inputs),
                language=proto_req.language or "en",
                favorite_places=list(proto_req.favorite_places),
                tariffs=list(proto_req.tariffs),
                timezone=proto_req.timezone or "UTC",
            )

            logger.info(
                "Chat RPC: session=%s user=%s text=%s audios=%d images=%d",
                request.session_id,
                request.user_id,
                bool(request.text),
                len(request.audios),
                len(request.images),
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
