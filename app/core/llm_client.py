import logging
import os
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import AsyncGenerator

import litellm
from dotenv import load_dotenv
from litellm.exceptions import (
    AuthenticationError,
    BadRequestError,
    ContextWindowExceededError,
    RateLimitError,
    ServiceUnavailableError,
)

load_dotenv()  # populate os.environ from .env before providers are built

from app.models.tools import TOOLS

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 5


# ---------------------------------------------------------------------------
# 1.  Configuration — loaded entirely from .env
# ---------------------------------------------------------------------------

@dataclass
class ModelEntry:
    litellm_name: str
    max_tokens: int = 8192


@dataclass
class ProviderConfig:
    name: str
    api_keys: list[str]        # actual key values (not env-var names)
    models: list[ModelEntry]
    base_url: str | None = None


def _parse_list(raw: str) -> list[str]:
    """Split a comma-separated env value into a clean list, dropping blanks."""
    return [item.strip() for item in raw.split(",") if item.strip()]


import re

# Known key format patterns — catches obvious typos before any request is sent.
_KEY_PATTERNS: dict[str, re.Pattern] = {
    "gemini":    re.compile(r"^AIzaSy[A-Za-z0-9_\-]{33}$"),   # exactly 39 chars
    "openai":    re.compile(r"^sk-"),
    "anthropic": re.compile(r"^sk-ant-"),
    "deepseek":  re.compile(r"^sk-"),
}


def _validate_keys(provider_name: str, keys: list[str]) -> list[str]:
    """
    Filter out keys that don't match the expected format for this provider.
    Logs a warning for each rejected key so you see the problem at startup.
    Returns only valid-looking keys.
    """
    pattern = _KEY_PATTERNS.get(provider_name)
    if pattern is None:
        return keys  # no pattern for this provider (ollama etc.) — keep all

    valid = []
    for key in keys:
        if pattern.match(key):
            valid.append(key)
        else:
            logger.warning(
                "Provider %s: key …%s looks malformed (expected pattern %s) — skipping",
                provider_name, key[-6:], pattern.pattern,
            )
    return valid


def _build_provider_configs() -> list[ProviderConfig]:
    """
    Build provider list purely from environment variables.
    Providers with no models defined are silently skipped.
    """
    max_tokens = int(os.environ.get("LLM_MAX_TOKENS", "8192"))

    # (provider_name, env_models_key, env_keys_key, base_url_env, fixed_base_url)
    provider_specs = [
        ("gemini",    "GEMINI_MODELS",    "GEMINI_API_KEYS",    None,             None),
        ("openai",    "OPENAI_MODELS",    "OPENAI_API_KEYS",    None,             None),
        ("anthropic", "ANTHROPIC_MODELS", "ANTHROPIC_API_KEYS", None,             None),
        ("deepseek",  "DEEPSEEK_MODELS",  "DEEPSEEK_API_KEYS",  None,             None),
        ("ollama",    "OLLAMA_MODELS",    None,                 "OLLAMA_BASE_URL", "http://localhost:11434"),
    ]


    configs = []
    for name, models_env, keys_env, base_url_env, default_base_url in provider_specs:
        raw_models = os.environ.get(models_env, "")
        if not raw_models.strip():
            logger.debug("Provider %s skipped — %s not set", name, models_env)
            continue

        models = [ModelEntry(m, max_tokens) for m in _parse_list(raw_models)]
        api_keys = _validate_keys(name, _parse_list(os.environ.get(keys_env, ""))) if keys_env else []
        base_url = (
            os.environ.get(base_url_env, default_base_url)
            if base_url_env
            else default_base_url
        )

        configs.append(ProviderConfig(
            name=name,
            api_keys=api_keys,
            models=models,
            base_url=base_url,
        ))
        logger.info(
            "Provider %s: %d model(s), %d key(s)%s",
            name, len(models), len(api_keys),
            f", base_url={base_url}" if base_url else "",
        )

    return configs


# ---------------------------------------------------------------------------
# 2.  Token-bucket — lightweight pre-flight rate-limit guard
# ---------------------------------------------------------------------------

@dataclass
class _Bucket:
    """Sliding-window request counter per (provider, api_key)."""
    capacity: int = 60          # max requests per window
    window_seconds: float = 60.0
    _timestamps: list[float] = field(default_factory=list)

    def available(self) -> bool:
        now = time.monotonic()
        cutoff = now - self.window_seconds
        self._timestamps = [t for t in self._timestamps if t > cutoff]
        return len(self._timestamps) < self.capacity

    def consume(self) -> None:
        self._timestamps.append(time.monotonic())


class RateLimitTracker:
    """
    Tracks per-(provider, key) usage and hard-lock-out times.
    Call `is_available(provider, key)` before a request.
    Call `mark_rate_limited(provider, key, retry_after)` when a 429 arrives.
    """
    def __init__(self) -> None:
        self._buckets: dict[tuple, _Bucket] = defaultdict(_Bucket)
        self._locked_until: dict[tuple, float] = {}

    def is_available(self, provider: str, key: str) -> bool:
        slot = (provider, key)
        locked = self._locked_until.get(slot, 0)
        if time.monotonic() < locked:
            logger.debug("Key %s…%s is locked out (%.0fs left)",
                         provider, key[-4:], locked - time.monotonic())
            return False
        return self._buckets[slot].available()

    def consume(self, provider: str, key: str) -> None:
        self._buckets[(provider, key)].consume()

    def mark_rate_limited(self, provider: str, key: str,
                          retry_after: float = 60.0) -> None:
        slot = (provider, key)
        self._locked_until[slot] = time.monotonic() + retry_after
        logger.warning("Key %s…%s locked out for %.0fs", provider, key[-4:], retry_after)

    def mark_auth_failed(self, provider: str, key: str) -> None:
        """Permanently disable a bad key for this process lifetime."""
        self._locked_until[(provider, key)] = float("inf")
        logger.error("Key %s…%s disabled (auth failure)", provider, key[-4:])


_tracker = RateLimitTracker()


# ---------------------------------------------------------------------------
# 3.  Exception → action classifier
# ---------------------------------------------------------------------------

def _classify_exception(exc: Exception) -> str:
    """
    Returns one of:
      "rotate_key"  — this key is exhausted/invalid; try next key
      "skip_model"  — this model is broken for this request; try next model
      "fatal"       — bad request we can't fix by switching
    """
    if isinstance(exc, RateLimitError):
        return "rotate_key"
    if isinstance(exc, AuthenticationError):
        return "rotate_key"   # bad key → rotate; mark_auth_failed called separately
    if isinstance(exc, ServiceUnavailableError):
        return "rotate_key"   # provider outage → try next key/provider
    if isinstance(exc, ContextWindowExceededError):
        return "skip_model"   # context too large → try bigger-context model
    if isinstance(exc, BadRequestError):
        return "fatal"        # malformed request; switching won't help
    # Generic network / timeout → try next key
    return "rotate_key"


def _extract_retry_after(exc: Exception) -> float:
    """Try to read Retry-After seconds from the exception."""
    try:
        return float(getattr(exc, "retry_after", None) or 60.0)
    except (TypeError, ValueError):
        return 60.0


_PROVIDERS = _build_provider_configs()


# ---------------------------------------------------------------------------
# 5.  Streaming delimiter
# ---------------------------------------------------------------------------

_ROUTE_DELIMITER = "<<<ROUTE>>>"
_ROUTE_DELIMITER_LEN = len(_ROUTE_DELIMITER)


# ---------------------------------------------------------------------------
# 6.  Core streaming functions
# ---------------------------------------------------------------------------

async def stream_response(
    messages: list[dict],
) -> AsyncGenerator[dict, None]:
    """
    Yields dicts:
      {"type": "text_chunk", "content": str}        — token as it arrives
      {"type": "done",       "route": str | None}   — end; route is a JSON array string or None
      {"type": "error",      "code": str, "message": str}
    """
    current_messages = list(messages)

    for round_num in range(MAX_TOOL_ROUNDS):
        got_tool_calls = False
        tool_calls_data: dict = {}

        async for event in _one_round_stream(current_messages):
            if event["type"] == "tool_calls":
                got_tool_calls = True
                tool_calls_data = event
                break
            yield event   # text_chunk, done, or error (error already returned by generator)

        if not got_tool_calls:
            return

        # Build next round with tool results
        tool_calls = tool_calls_data["tool_calls"]
        current_messages.append({
            "role": "assistant",
            "content": tool_calls_data.get("content") or None,
            "tool_calls": [
                {"id": tc["id"], "type": "function",
                 "function": {"name": tc["name"], "arguments": tc["arguments"]}}
                for tc in tool_calls
            ],
        })
        current_messages.extend(await _execute_tool_calls(tool_calls))
        logger.debug("Tool round %d/%d complete", round_num + 1, MAX_TOOL_ROUNDS)

    yield {"type": "error", "code": "MAX_ROUNDS", "message": "Tool loop limit reached"}



async def _one_round_stream(
    messages: list[dict],
) -> AsyncGenerator[dict, None]:
    """Try every provider → key → model; stream from the first that responds."""
    for provider in _PROVIDERS:
        keys = provider.api_keys or [None]

        for api_key in keys:
            key_id = (api_key or "")[-4:] or "local"

            if api_key and not _tracker.is_available(provider.name, api_key):
                logger.info("Skipping %s key …%s (pre-flight)", provider.name, key_id)
                continue

            for model_entry in provider.models:
                got_first_chunk = False
                try:
                    async for event in _call_model_stream(provider, api_key, model_entry, messages):
                        got_first_chunk = True
                        yield event
                    if api_key:
                        _tracker.consume(provider.name, api_key)
                    return  # success

                except Exception as exc:
                    if got_first_chunk:
                        # Already streaming to the user — can't switch provider now
                        yield {"type": "error", "code": "STREAM_INTERRUPTED", "message": str(exc)}
                        return

                    action = _classify_exception(exc)
                    logger.warning("[%s/…%s/%s] %s → %s",
                                   provider.name, key_id, model_entry.litellm_name,
                                   type(exc).__name__, action)

                    if action == "rotate_key":
                        if isinstance(exc, RateLimitError) and api_key:
                            _tracker.mark_rate_limited(provider.name, api_key, _extract_retry_after(exc))
                        elif isinstance(exc, AuthenticationError) and api_key:
                            _tracker.mark_auth_failed(provider.name, api_key)
                        break  # next key
                    elif action == "skip_model":
                        continue  # next model
                    else:
                        yield {"type": "error", "code": "BAD_REQUEST", "message": str(exc)}
                        return

    yield {"type": "error", "code": "ALL_PROVIDERS_FAILED",
           "message": "Every provider, key, and model was exhausted."}


async def _call_model_stream(
    provider: ProviderConfig,
    api_key: str | None,
    model_entry: ModelEntry,
    messages: list[dict],
) -> AsyncGenerator[dict, None]:
    """
    Stream one LLM call, detecting <<<ROUTE>>> in the output.
    Yields:
      {"type": "text_chunk", "content": str}                      — while text is arriving
      {"type": "done",       "route": str | None}                 — end of text response
      {"type": "tool_calls", "tool_calls": list, "content": str}  — if model called tools
    Raises litellm exceptions on API/network failure.
    """
    kwargs: dict = dict(
        model=model_entry.litellm_name,
        messages=messages,
        max_tokens=model_entry.max_tokens,
        stream=True,
    )
    if api_key:
        kwargs["api_key"] = api_key
    if provider.base_url:
        kwargs["api_base"] = provider.base_url
    if TOOLS:
        kwargs["tools"] = TOOLS
        kwargs["tool_choice"] = "auto"

    logger.info("→ %s / …%s / %s",
                provider.name, (api_key or "")[-4:] or "local", model_entry.litellm_name)

    response = await litellm.acompletion(**kwargs)

    text_buffer = ""     # chars not yet yielded (kept to detect split delimiter)
    route_buffer = ""
    delimiter_found = False
    tool_calls: list[dict] = []

    async for chunk in response:
        delta = chunk.choices[0].delta if chunk.choices else None
        if delta is None:
            continue

        # Accumulate tool calls (buffered — not streamed)
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

        content = delta.content or ""
        if not content or tool_calls:
            # Don't stream text if we're in a tool-call response
            continue

        if delimiter_found:
            route_buffer += content
        else:
            text_buffer += content
            idx = text_buffer.find(_ROUTE_DELIMITER)
            if idx != -1:
                delimiter_found = True
                before = text_buffer[:idx].rstrip("\n").rstrip()
                if before:
                    yield {"type": "text_chunk", "content": before}
                route_buffer = text_buffer[idx + _ROUTE_DELIMITER_LEN:]
            else:
                # Yield text that's safely past a possible split delimiter
                safe_len = max(0, len(text_buffer) - _ROUTE_DELIMITER_LEN + 1)
                if safe_len > 0:
                    yield {"type": "text_chunk", "content": text_buffer[:safe_len]}
                    text_buffer = text_buffer[safe_len:]

    # --- End of stream ---
    if tool_calls:
        yield {"type": "tool_calls", "tool_calls": tool_calls, "content": ""}
        return

    # Flush any remaining text buffer (no delimiter found in it)
    if not delimiter_found and text_buffer:
        yield {"type": "text_chunk", "content": text_buffer}

    yield {"type": "done", "route": route_buffer.strip() if delimiter_found else None}


# ---------------------------------------------------------------------------
# 6.  Tool execution (stub — replace with your actual dispatch logic)
# ---------------------------------------------------------------------------

async def _execute_tool_calls(tool_calls: list[dict]) -> list[dict]:
    """
    Execute tool calls and return tool-result messages.
    Replace the body with your real tool dispatcher.
    """
    results = []
    for tc in tool_calls:
        try:
            # --- plug your tool logic here ---
            tool_result = f"[Tool '{tc['name']}' executed with args: {tc['arguments']}]"
        except Exception as exc:
            tool_result = f"[Tool '{tc['name']}' error: {exc}]"

        results.append({
            "role": "tool",
            "tool_call_id": tc["id"],
            "content": tool_result,
        })
    return results