"""
test_grpc.py — manual gRPC test script

Usage:
    python test_grpc.py                     # run all cases
    python test_grpc.py text                # text only
    python test_grpc.py audio               # audio only  (needs test.wav)
    python test_grpc.py image               # image only  (needs test.jpg)
    python test_grpc.py all                 # text + audio + image together
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


async def run(label: str, **kwargs) -> None:
    """Send one ChatRequest with any combination of text/audio/image."""
    print(f"\n{'='*50}")
    print(f"TEST: {label}")
    print(f"{'='*50}")

    async with grpc.aio.insecure_channel(SERVER) as channel:
        stub = chat_pb2_grpc.ChatServiceStub(channel)

        async def requests():
            yield chat_pb2.ChatRequest(
                session_id=SESSION,
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


async def main(case: str = "all_cases") -> None:

    # ── Text only ────────────────────────────────────────────────
    if case in ("text", "all_cases"):
        await run(
            "Text only",
            text_input="I need a ride from Dubai Mall to Dubai Airport",
        )

    # ── Multi-stop text ──────────────────────────────────────────
    if case in ("multi", "all_cases"):
        await run(
            "Multi-stop text",
            text_input="Pick me up from Burj Khalifa, stop at City Walk, then drop me at Palm Jumeirah",
        )

    # ── Audio only ───────────────────────────────────────────────
    if case in ("audio", "all_cases"):
        audio_file = Path("test.wav")
        if not audio_file.exists():
            print("SKIP audio — test.wav not found (put any WAV file next to this script)")
        else:
            await run(
                "Audio only",
                audio_input=audio_file.read_bytes(),
            )

    # ── Image only ───────────────────────────────────────────────
    if case in ("image", "all_cases"):
        image_file = next(
            (Path(p) for p in ("test.jpg", "test.jpeg", "test.png") if Path(p).exists()),
            None,
        )
        if image_file is None:
            print("SKIP image — no test.jpg / test.png found next to this script")
        else:
            await run(
                f"Image only ({image_file.name})",
                image_input=image_file.read_bytes(),
            )

    # ── Text + Audio together ────────────────────────────────────
    if case in ("text_audio", "all_cases"):
        audio_file = Path("test.wav")
        if not audio_file.exists():
            print("SKIP text+audio — test.wav not found")
        else:
            await run(
                "Text + Audio combined",
                text_input="The destination is shown in the voice note",
                audio_input=audio_file.read_bytes(),
            )

    # ── Text + Image together ────────────────────────────────────
    if case in ("text_image", "all_cases"):
        image_file = next(
            (Path(p) for p in ("test.jpg", "test.jpeg", "test.png") if Path(p).exists()),
            None,
        )
        if image_file is None:
            print("SKIP text+image — no test.jpg / test.png found")
        else:
            await run(
                "Text + Image combined",
                text_input="Take me to this place",
                image_input=image_file.read_bytes(),
            )

    # ── All three together ───────────────────────────────────────
    if case in ("all", "all_cases"):
        audio_file = Path("test.wav")
        image_file = next(
            (Path(p) for p in ("test.jpg", "test.jpeg", "test.png") if Path(p).exists()),
            None,
        )
        if not audio_file.exists() or image_file is None:
            print("SKIP all-three — need both test.wav and test.jpg")
        else:
            await run(
                "Text + Audio + Image combined",
                text_input="Take me to this place at the end then get me place that i showed in picture",
                audio_input=audio_file.read_bytes(),
                image_input=image_file.read_bytes(),
            )


if __name__ == "__main__":
    case = sys.argv[1] if len(sys.argv) > 1 else "all_cases"
    asyncio.run(main(case))
