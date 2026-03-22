"""app/processors/image.py — Prepares image bytes for vision model input."""

import base64


def to_base64_url(image_bytes: bytes, mime_type: str = "image/jpeg") -> str:
    """Return a data-URL string suitable for OpenAI vision content blocks."""
    encoded = base64.b64encode(image_bytes).decode("utf-8")
    return f"data:{mime_type};base64,{encoded}"