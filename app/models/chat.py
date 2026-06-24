"""app/models/chat.py — ChatRequest / ChatResponse Pydantic models."""
from typing import List, Optional
from pydantic import BaseModel


class Tariff(BaseModel):
    id:          str
    name:        str
    description: str = ""


class ChatRequest(BaseModel):
    session_id:       str
    user_id:          str
    text:             Optional[str]  = None
    audios:           List[bytes]    = []
    images:           List[bytes]    = []
    language:         str            = "en"
    favorite_places:  List[str]      = []  
    tariffs:          List[Tariff]   = []  
    timezone:         str            = "UTC"


class ChatResponse(BaseModel):
    session_id: str
    text_chunk:  Optional[str]  = None
    is_final:    bool = False
    order_draft: Optional[dict] = None
    action:      Optional[dict] = None
    error:       Optional[dict] = None