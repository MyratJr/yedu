"""app/models/chat.py — ChatRequest / ChatResponse Pydantic models."""
from typing import Optional
from pydantic import BaseModel


class ChatRequest(BaseModel):
    session_id: str
    user_id:    str
    text:       Optional[str]   = None
    audio:      Optional[bytes] = None
    image:      Optional[bytes] = None
    language:   str = "en"


class ChatResponse(BaseModel):
    session_id: str
    text_chunk:  Optional[str]  = None
    is_final:    bool = False
    order_draft: Optional[dict] = None
    action:      Optional[dict] = None
    error:       Optional[dict] = None