import os
import logging
from typing import AsyncGenerator
import litellm
from app.core.config import get_settings
from app.models.tools import TOOLS
from app.tools.geocode import geocode_address, reverse_geocode
from app.tools.places_search import search_places
from app.tools.device_location import request_user_location
import json

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 5

MODELS = [
    "gemini/gemini-2.5-flash",
    "gemini/gemini-2.0-flash-lite",
    "claude-sonnet-4-20250514",
    "gpt-4o",
]


def _setup_keys() -> None:
    settings = get_settings()
    if settings.anthropic_api_key:
        os.environ["ANTHROPIC_API_KEY"] = settings.anthropic_api_key
    if settings.gemini_api_key:
        os.environ["GEMINI_API_KEY"]    = settings.gemini_api_key
        os.environ["GOOGLE_API_KEY"]    = settings.gemini_api_key  # ← add this
    if settings.openai_api_key:
        os.environ["OPENAI_API_KEY"]    = settings.openai_api_key
    litellm.api_base = None


async def stream_response(
    messages: list[dict],
) -> AsyncGenerator[dict, None]:
    _setup_keys()

    current_messages = list(messages)

    for round_num in range(MAX_TOOL_ROUNDS):
        response = None
        last_error = None

        # Try each model in order until one produces a complete response
        collected_text = ""
        tool_calls: list[dict] = []
        got_response = False

        for model in MODELS:
            try:
                logger.info("Trying model: %s", model)
                response = await litellm.acompletion(
                    model=model,
                    messages=current_messages,
                    tools=TOOLS,
                    tool_choice="auto",
                    stream=True,
                )

                # Buffer the stream — errors during iteration also fall through
                collected_text = ""
                tool_calls = []
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

                got_response = True
                break  # stream complete — stop trying models
            except Exception as exc:
                logger.warning("Model %s failed: %s — trying next", model, exc)
                last_error = exc
                continue

        if not got_response:
            logger.error("All models failed. Last error: %s", last_error)
            yield {"type": "error", "code": "ALL_MODELS_FAILED", "message": str(last_error)}
            return

        # Now stream buffered text to caller
        if collected_text:
            yield {"type": "text", "content": collected_text, "is_final": False}

        # No tool calls → final response
        if not tool_calls:
            yield {"type": "text", "content": "", "is_final": True}
            return

        # Execute tools and loop back
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

        for tc in tool_calls:
            if tc["name"] == "request_user_location":
                yield {"type": "action", "action_type": "REQUEST_GPS", "payload": ""}

            args = json.loads(tc["arguments"] or "{}")
            tool_result = await _execute_tool(tc["name"], args)
            current_messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": tool_result,
            })

        logger.debug("Tool round %d complete", round_num + 1)

    yield {"type": "error", "code": "MAX_ROUNDS", "message": "Tool loop limit reached"}


async def _execute_tool(name: str, args: dict) -> str:
    try:
        if name == "search_places":
            result = await search_places(query=args["query"], language=args.get("language", "en"))
        elif name == "geocode_address":
            result = await geocode_address(args["address"])
        elif name == "reverse_geocode":
            result = await reverse_geocode(latitude=args["latitude"], longitude=args["longitude"])
        elif name == "request_user_location":
            result = await request_user_location()
        else:
            result = {"error": f"Unknown tool: {name}"}
    except Exception as exc:
        result = {"error": str(exc)}
    return json.dumps(result)