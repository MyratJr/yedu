"""
app/core/router.py

Detects input type (text / voice / image), preprocesses it into
plain text, then drives the LLM + streaming pipeline.
"""

from __future__ import annotations

import logging
from typing import AsyncGenerator

from app.core import llm_client, prompt_builder, response_parser, stream_handler
from app.models.chat import ChatRequest, InputType
from app.processors import preprocess, to_base64_url, transcribe
from app.session.manager import session_manager

logger = logging.getLogger(__name__)


async def handle(request: ChatRequest) -> AsyncGenerator[dict, None]:
    """
    Main entry point. Yields gRPC ChatResponse protobuf messages.
    """
    # 1. Resolve input → plain text
    user_text = await _resolve_input(request)
    if not user_text:
        yield stream_handler.make_error("EMPTY_INPUT", "No input received")
        return

    # 2. Load session history + location
    history  = await session_manager.get_history(request.session_id)
    location = await session_manager.get_location(request.session_id)

    # 3. Build messages for LLM
    messages = prompt_builder.build_messages(
        user_text=user_text,
        history=history,
        language=request.language,
        location=location,
    )

    # 4. Save user message to history
    await session_manager.append_message(request.session_id, "user", user_text)

    # 5. Stream LLM response
    full_text = ""
    async for event in llm_client.stream_response(messages):
        if event["type"] == "text":
            full_text += event["content"]
            yield stream_handler.make_text_chunk(
                text=event["content"],
                is_final=event.get("is_final", False),
            )

        elif event["type"] == "action":
            yield stream_handler.make_action(
                action_type=event["action_type"],
                payload=event.get("payload", ""),
            )

        elif event["type"] == "error":
            yield stream_handler.make_error(
                code=event["code"],
                message=event["message"],
            )
            return

    # 6. Check for order draft in the full response
    draft = response_parser.extract_order_draft(full_text)
    if draft and draft.is_complete():
        yield stream_handler.make_order_draft(draft)

    # 7. Save assistant reply to history (strip the order_draft tag)
    clean_text = response_parser.strip_order_draft_tag(full_text)
    await session_manager.append_message(
        request.session_id, "assistant", clean_text
    )


async def _resolve_input(request: ChatRequest) -> str:
    """Convert any input type to plain text."""
    print("1-->")
    if request.input_type == InputType.text:
        print("2-->")
        return preprocess(request.text or "")

    if request.input_type == InputType.audio:
        print("3-->")
        if not request.audio:
            return ""
        logger.debug("Transcribing audio for session %s", request.session_id)
        return await transcribe(request.audio)

    if request.input_type == InputType.image:
        if not request.image:
            return ""
        image_url = to_base64_url(request.image)
        return f"[User sent an image: {image_url[:60]}...]"

    return ""