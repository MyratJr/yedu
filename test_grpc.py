"""
test_grpc.py — manual gRPC test script

Usage:
    python test_grpc.py                     # run all cases
    python test_grpc.py text                # text only
    python test_grpc.py audio               # audio only  (needs test.wav)
    python test_grpc.py image               # image only  (needs test.jpg)
    python test_grpc.py multi_image         # multiple images as route points
    python test_grpc.py multi_audio         # multiple audio clips combined
    python test_grpc.py all                 # text + audio + image together
    python test_grpc.py conv_pickup         # multi-turn: pickup first, then destination
    python test_grpc.py conv_dest           # multi-turn: destination first, then pickup
"""

import asyncio
import sys
from pathlib import Path

import grpc
from app.proto import chat_pb2, chat_pb2_grpc

SERVER = "localhost:50051"
SESSION = "test-sess-1"
USER = "test-user-1"


def print_response(response) -> None:
    if response.HasField("text_chunk"):
        print(response.text_chunk.text, end="", flush=True)
    elif response.HasField("order_draft"):
        d = response.order_draft
        print("\n\n--- ORDER DRAFT ---")
        print(f"  Pickup:      {d.pickup_address}")
        print(f"  Destination: {d.destination_address}")
        for i, stop in enumerate(d.stops, 1):
            print(f"  Stop {i}:      {stop.address}")
        print(f"  Ride type:   {d.ride_type}")
    elif response.HasField("action"):
        print(f"\n--- ACTION: {response.action.type} ---")
    elif response.HasField("error"):
        print(f"\n--- ERROR: {response.error.code} — {response.error.message} ---")


async def run(label: str, session_id: str = SESSION, **kwargs) -> None:
    """Send one ChatRequest with any combination of text/audios/images."""
    print(f"\n{'='*50}")
    print(f"TEST: {label}")
    print(f"{'='*50}")

    async with grpc.aio.insecure_channel(SERVER) as channel:
        stub = chat_pb2_grpc.ChatServiceStub(channel)

        async def requests():
            yield chat_pb2.ChatRequest(
                session_id=session_id,
                user_id=USER,
                language="en",
                **kwargs,
            )

        try:
            async for response in stub.Chat(requests()):
                print_response(response)
        except grpc.aio.AioRpcError as e:
            print(f"gRPC error: {e.code()} — {e.details()}")

    print("\n")


async def run_conversation(label: str, turns: list[dict]) -> None:
    """
    Simulate a multi-turn conversation.
    Each turn is a dict of kwargs for ChatRequest (text_input, audio_inputs, image_inputs).
    All turns share the same session_id so history accumulates.
    """
    import uuid
    session_id = f"conv-{uuid.uuid4().hex[:8]}"
    print(f"\n{'='*50}")
    print(f"CONVERSATION: {label}  (session={session_id})")
    print(f"{'='*50}")

    for i, turn_kwargs in enumerate(turns, 1):
        print(f"\n--- Turn {i} ---")
        if "text_input" in turn_kwargs:
            print(f"  User: {turn_kwargs['text_input']}")
        print(f"  AI  : ", end="", flush=True)
        await run(f"turn {i}", session_id=session_id, **turn_kwargs)
    print()


def _find_images() -> list[Path]:
    """Return all test images found next to this script (test.jpg, test2.jpg, …)."""
    candidates = []
    for ext in ("jpg", "jpeg", "png"):
        candidates += sorted(Path(".").glob(f"test*.{ext}"))
    return candidates


def _find_audios() -> list[Path]:
    """Return all test audio files found next to this script (test.wav, test2.wav, …)."""
    return sorted(Path(".").glob("test*.wav"))


async def main(case: str = "all_cases") -> None:

    # ── Text only ────────────────────────────────────────────────
    if case in ("text", "all_cases"):
        await run(
            "Text only",
            text_input="make london eye as a second stop",
        )

    # ── Multi-stop text ──────────────────────────────────────────
    if case in ("multi", "all_cases"):
        await run(
            "Multi-stop text",
            text_input="Pick me up from Burj Khalifa, stop at City Walk, then drop me at Palm Jumeirah",
        )

    # ── Audio only (single) ──────────────────────────────────────
    if case in ("audio", "all_cases"):
        audios = _find_audios()
        if not audios:
            print("SKIP audio — no test*.wav found next to this script")
        else:
            await run(
                f"Audio only ({audios[0].name})",
                audio_inputs=[audios[0].read_bytes()],
            )

    # ── Multiple audio clips ──────────────────────────────────────
    if case in ("multi_audio", "all_cases"):
        audios = _find_audios()
        if len(audios) < 2:
            print("SKIP multi_audio — need at least test.wav and test2.wav")
        else:
            await run(
                f"Multiple audio ({', '.join(a.name for a in audios)})",
                audio_inputs=[a.read_bytes() for a in audios],
            )

    # ── Image only (single) ──────────────────────────────────────
    if case in ("image", "all_cases"):
        images = _find_images()
        if not images:
            print("SKIP image — no test*.jpg / test*.png found next to this script")
        else:
            await run(
                f"Image only ({images[0].name})",
                image_inputs=[images[0].read_bytes()],
            )

    # ── Multiple images as route points ──────────────────────────
    if case in ("multi_image", "all_cases"):
        images = _find_images()
        if len(images) < 2:
            print("SKIP multi_image — need at least test.jpg and test2.jpg")
        else:
            await run(
                f"Multiple images as route ({', '.join(i.name for i in images)})",
                image_inputs=[i.read_bytes() for i in images],
            )

    # ── Text + Audio together ────────────────────────────────────
    if case in ("text_audio", "all_cases"):
        audios = _find_audios()
        if not audios:
            print("SKIP text+audio — test*.wav not found")
        else:
            await run(
                "Text + Audio combined",
                text_input="Then my destination is Yyltyz hotel",
                audio_inputs=[a.read_bytes() for a in audios],
            )

    # ── Text + Image together ────────────────────────────────────
    if case in ("text_image", "all_cases"):
        images = _find_images()
        if not images:
            print("SKIP text+image — no test*.jpg / test*.png found")
        else:
            await run(
                "Text + Image combined",
                text_input="make destination this",
                image_inputs=[i.read_bytes() for i in images],
            )

    # ── All three together ───────────────────────────────────────
    if case in ("all", "all_cases"):
        audios = _find_audios()
        images = _find_images()
        if not audios or not images:
            print("SKIP all-three — need at least test.wav and test.jpg")
        else:
            await run(
                "Text + Audio + Image combined",
                text_input="my pickup and last point in voice and stops will be in picture, i want add one more stop for Berkarar",
                audio_inputs=[a.read_bytes() for a in audios],
                image_inputs=[i.read_bytes() for i in images],
            )


    # ── Multi-turn: pickup only → AI asks destination → user replies ────────
    if case in ("conv_pickup", "all_cases"):
        await run_conversation(
            "Pickup first, then destination",
            turns=[
                {"text_input": "pick me up from my location"},
                {"text_input": "Yyldyz Hotel"},
            ],
        )

    # ── Multi-turn: destination only → AI asks pickup → user replies ─────────
    if case in ("conv_dest", "all_cases"):
        await run_conversation(
            "Destination first, then pickup",
            turns=[
                {"text_input": "I want to go to Berkarar Mall"},
                {"text_input": "my current location"},
            ],
        )


if __name__ == "__main__":
    case = sys.argv[1] if len(sys.argv) > 1 else "all_cases"
    asyncio.run(main(case))
