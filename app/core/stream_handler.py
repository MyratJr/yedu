"""
app/core/stream_handler.py

Converts internal event dicts from llm_client into gRPC ChatResponse messages.
"""

from __future__ import annotations

from app.models.order import OrderDraft
from app.proto import chat_pb2  # type: ignore[import]


def make_text_chunk(text: str, is_final: bool = False) -> chat_pb2.ChatResponse:
    return chat_pb2.ChatResponse(
        text_chunk=chat_pb2.TextChunk(text=text, is_final=is_final)
    )


def make_order_draft(draft: OrderDraft) -> chat_pb2.ChatResponse:
    stops = [
        chat_pb2.StopMsg(address=s.address, lat=s.latitude, lng=s.longitude)
        for s in draft.stops
    ]
    return chat_pb2.ChatResponse(
        order_draft=chat_pb2.OrderDraftMsg(
            pickup_address=draft.pickup.address,
            pickup_lat=draft.pickup.latitude,
            pickup_lng=draft.pickup.longitude,
            destination_address=draft.destination.address,
            destination_lat=draft.destination.latitude,
            destination_lng=draft.destination.longitude,
            stops=stops,
            ride_type=draft.ride_type,
            notes=draft.notes or "",
        )
    )


def make_action(action_type: str, payload: str = "") -> chat_pb2.ChatResponse:
    type_map = {
        "REQUEST_GPS":    chat_pb2.ActionRequest.ActionType.REQUEST_GPS,
        "CONFIRM_ORDER":  chat_pb2.ActionRequest.ActionType.CONFIRM_ORDER,
    }
    return chat_pb2.ChatResponse(
        action=chat_pb2.ActionRequest(
            type=type_map.get(action_type, chat_pb2.ActionRequest.ActionType.UNKNOWN),
            payload=payload,
        )
    )


def make_error(code: str, message: str) -> chat_pb2.ChatResponse:
    return chat_pb2.ChatResponse(
        error=chat_pb2.ErrorInfo(code=code, message=message)
    )