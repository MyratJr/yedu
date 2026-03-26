"""
app/core/router.py

Detects input type (text / voice / image), preprocesses it into
plain text, then drives the LLM + streaming pipeline.
Session history is loaded before the LLM call and updated afterwards,
enabling multi-turn conversations (e.g. ask for missing pickup/destination).
"""

from __future__ import annotations

import logging
from typing import AsyncGenerator

from app.core import llm_client, prompt_builder, stream_handler
from app.models.chat import ChatRequest
from app.processors import preprocess, to_base64_url, transcribe
from app.session.manager import session_manager

logger = logging.getLogger(__name__)

# Status chunks shown to the client while input is being processed, per language.
_STATUS: dict[str, dict[str, str]] = {
    "en": {
        "text":        "Analyzing your message...\n",
        "voice_one":   "Analyzing voice message...\n",
        "voice_many":  "Analyzing {n} voice messages...\n",
        "image_one":   "Analyzing image...\n",
        "image_many":  "Analyzing {n} images...\n",
    },
    "ar": {
        "text":        "جارٍ تحليل رسالتك...\n",
        "voice_one":   "جارٍ تحليل الرسالة الصوتية...\n",
        "voice_many":  "جارٍ تحليل {n} رسائل صوتية...\n",
        "image_one":   "جارٍ تحليل الصورة...\n",
        "image_many":  "جارٍ تحليل {n} صور...\n",
    },
    "ru": {
        "text":        "Анализирую ваше сообщение...\n",
        "voice_one":   "Анализирую голосовое сообщение...\n",
        "voice_many":  "Анализирую {n} голосовых сообщения...\n",
        "image_one":   "Анализирую изображение...\n",
        "image_many":  "Анализирую {n} изображения...\n",
    },
    "tr": {
        "text":        "Mesajınız analiz ediliyor...\n",
        "voice_one":   "Sesli mesaj analiz ediliyor...\n",
        "voice_many":  "{n} sesli mesaj analiz ediliyor...\n",
        "image_one":   "Görsel analiz ediliyor...\n",
        "image_many":  "{n} görsel analiz ediliyor...\n",
    },
}


def _status(language: str, key: str, n: int = 0) -> str:
    lang = _STATUS.get(language, _STATUS["en"])
    return lang[key].format(n=n)


async def handle(request: ChatRequest) -> AsyncGenerator[dict, None]:
    """
    Main entry point. Yields gRPC ChatResponse protobuf messages.
    """
    lang = request.language

    # 1. Emit per-type status chunks in the client's language
    if request.text:
        yield stream_handler.make_text_chunk(_status(lang, "text"), is_final=False)

    if request.audios:
        n = len(request.audios)
        key = "voice_one" if n == 1 else "voice_many"
        yield stream_handler.make_text_chunk(_status(lang, key, n), is_final=False)

    if request.images:
        n = len(request.images)
        key = "image_one" if n == 1 else "image_many"
        yield stream_handler.make_text_chunk(_status(lang, key, n), is_final=False)

    # 2. Resolve all inputs → LLM content + plain text for history
    user_content, history_text = await _resolve_input(request)
    if not user_content:
        yield stream_handler.make_error("EMPTY_INPUT", "No input received")
        return

    # 3. Load existing history and save the new user turn
    history = await session_manager.get_history(request.session_id)
    await session_manager.append_message(request.session_id, "user", history_text)


    # 4. Build messages: [system, ...history, user]
    messages = prompt_builder.build_messages(
        user_content=user_content,
        history=history,
        language=request.language,
        favorite_places=request.favorite_places,
    )

    # 5. Stream LLM response — text chunks arrive word-by-word, route comes at the end
    full_text = ""
    async for event in llm_client.stream_response(messages):
        if event["type"] == "text_chunk":
            full_text += event["content"]
            yield stream_handler.make_text_chunk(event["content"], is_final=False)

        elif event["type"] == "done":
            route_str = event.get("route")
            if route_str:
                yield stream_handler.make_text_chunk(route_str, is_final=True)
            else:
                yield stream_handler.make_text_chunk("", is_final=True)
            break

        elif event["type"] == "error":
            yield stream_handler.make_error(
                code=event["code"],
                message=event["message"],
            )
            return

    # 6. Persist assistant reply so next turn has full context
    if full_text:
        await session_manager.append_message(
            request.session_id, "assistant", full_text
        )


async def _resolve_input(request: ChatRequest) -> tuple[str | list, str]:
    """
    Process all inputs and return:
      - llm_content: str (text only) or list of content parts (when images present)
      - history_text: plain text to store in session history
    """
    text_parts = []

    if request.text:
        text_parts.append(preprocess(request.text))

    # Transcribe all audio clips and append in order
    for i, audio in enumerate(request.audios):
        logger.debug(
            "Transcribing audio %d/%d for session %s",
            i + 1, len(request.audios), request.session_id,
        )
        transcribed = await transcribe(audio)
        if transcribed:
            text_parts.append(transcribed)

    history_text = "\n".join(text_parts)

    if request.images:
        # Build multimodal content list — images in order (1st=pickup, last=destination)
        content: list = []

        if history_text:
            content.append({"type": "text", "text": history_text})
        elif len(request.images) == 1:
            content.append({"type": "text", "text": "Take me to the place shown in this image."})
        else:
            content.append({
                "type": "text",
                "text": (
                    f"I have {len(request.images)} images. "
                    "Image 1 is my pickup location, "
                    + (
                        f"images 2–{len(request.images) - 1} are stops along the way, "
                        if len(request.images) > 2 else ""
                    )
                    + f"and image {len(request.images)} is my destination."
                ),
            })

        for idx, image_bytes in enumerate(request.images):
            label = _image_label(idx, len(request.images))
            content.append({"type": "text", "text": label})
            content.append({"type": "image_url", "image_url": {"url": to_base64_url(image_bytes)}})

        if not history_text:
            history_text = f"[{len(request.images)} image(s)]"
        return content, history_text

    return history_text, history_text


def _image_label(idx: int, total: int) -> str:
    if total == 1:
        return "Image (destination):"
    if idx == 0:
        return "Image 1 (pickup):"
    if idx == total - 1:
        return f"Image {idx + 1} (destination):"
    return f"Image {idx + 1} (stop {idx}):"
