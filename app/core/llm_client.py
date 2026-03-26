import os
import logging
from typing import AsyncGenerator
import litellm
from app.core.config import get_settings
from app.models.tools import TOOLS

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 5

MODELS = [
    "gemini/gemini-2.5-flash",
    "gemini/gemini-2.0-flash",
    "claude-sonnet-4-20250514",
    "gpt-4o",
]


def _setup_keys() -> None:
    settings = get_settings()
    if settings.anthropic_api_key:
        os.environ["ANTHROPIC_API_KEY"] = settings.anthropic_api_key
    if settings.gemini_api_key:
        os.environ["GEMINI_API_KEY"] = settings.gemini_api_key
        os.environ["GOOGLE_API_KEY"] = settings.gemini_api_key
    if settings.openai_api_key:
        os.environ["OPENAI_API_KEY"] = settings.openai_api_key
    litellm.api_base = None


async def stream_response(
    messages: list[dict],
) -> AsyncGenerator[dict, None]:
    _setup_keys()

    current_messages = list(messages)

    for round_num in range(MAX_TOOL_ROUNDS):
        last_error = None
        collected_text = ""
        tool_calls: list[dict] = []
        got_response = False

        for model in MODELS:
            try:
                logger.info("Trying model: %s", model)
                kwargs: dict = dict(
                    model=model,
                    messages=current_messages,
                    stream=True,
                )
                if TOOLS:
                    kwargs["tools"] = TOOLS
                    kwargs["tool_choice"] = "auto"

                response = await litellm.acompletion(**kwargs)

                collected_text = ""
                tool_calls = []

                # Accumulate all chunks — do NOT stream partial JSON to caller
                async for chunk in response:
                    delta = chunk.choices[0].delta if chunk.choices else None
                    if delta is None:
                        continue

                    if delta.content:
                        collected_text += delta.content

                    if delta.tool_calls:
                        for tc in delta.tool_calls:
                            idx = tc.index
                            while len(tool_calls) <= idx:
                                tool_calls.append({"id": "", "name": "", "arguments": ""})
                            if tc.id:
                                tool_calls[idx]["id"] = tc.id
                            if tc.function:
                                if tc.function.name:
                                    tool_calls[idx]["name"] += tc.function.name
                                if tc.function.arguments:
                                    tool_calls[idx]["arguments"] += tc.function.arguments

                # Yield the full response as one final chunk
                if collected_text and not tool_calls:
                    yield {"type": "text", "content": collected_text, "is_final": True}

                got_response = True
                break

            except Exception as exc:
                logger.warning("Model %s failed: %s — trying next", model, exc)
                last_error = exc
                continue

        if not got_response:
            logger.error("All models failed. Last error: %s", last_error)
            yield {"type": "error", "code": "ALL_MODELS_FAILED", "message": str(last_error)}
            return

        if not tool_calls:
            return

        current_messages.append({
            "role": "assistant",
            "content": collected_text or None,
            "tool_calls": [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": tc["arguments"],
                    },
                }
                for tc in tool_calls
            ],
        })

        logger.debug("Tool round %d complete", round_num + 1)

    yield {"type": "error", "code": "MAX_ROUNDS", "message": "Tool loop limit reached"}