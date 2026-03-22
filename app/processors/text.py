"""app/processors/text.py — Text preprocessing."""


def preprocess(text: str) -> str:
    """Normalize whitespace and strip leading/trailing space."""
    return " ".join(text.split()).strip()