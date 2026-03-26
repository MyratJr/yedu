from __future__ import annotations

from app.proto import chat_pb2  


def make_text_chunk(text: str, is_final: bool = False) -> chat_pb2.ChatResponse:
    return chat_pb2.ChatResponse(
        text_chunk=chat_pb2.TextChunk(text=text, is_final=is_final)
    )


def make_error(code: str, message: str) -> chat_pb2.ChatResponse:
    return chat_pb2.ChatResponse(
        error=chat_pb2.ErrorInfo(code=code, message=message)
    )