"""
test_grpc.py — manual gRPC test script

Usage:
    python test_grpc.py                     # run all cases
    python test_grpc.py text                # text only
    python test_grpc.py audio               # audio only  (needs test.wav)
    python test_grpc.py image               # image only  (needs test.jpg)
    python test_grpc.py multi_image         # multiple images as route points
    python test_grpc.py multi_audio         # multiple audio clips combined
    python test_grpc.py text_audio          # text + audio together
    python test_grpc.py text_image          # text + image together
    python test_grpc.py all                 # text + audio + image together
    python test_grpc.py fav_places          # favorite places resolution
    python test_grpc.py conv_pickup         # multi-turn: pickup first, then destination
"""

import asyncio
import sys
from pathlib import Path

import grpc
from app.proto import chat_pb2, chat_pb2_grpc

SERVER  = "localhost:50051"
SESSION = "test-sess-1"
USER    = "test-user-1"


def print_response(response) -> None:
    if response.HasField("text_chunk"):
        print(response.text_chunk.text, end="", flush=True)
    elif response.HasField("error"):
        print(f"\n--- ERROR: {response.error.code} — {response.error.message} ---")


async def run(label: str, session_id: str = SESSION, **kwargs) -> None:
    """Send one ChatRequest with any combination of text/audios/images/favorite_places."""
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
    Each turn is a dict of kwargs for ChatRequest.
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
    candidates = []
    for ext in ("jpg", "jpeg", "png"):
        candidates += sorted(Path(".").glob(f"test*.{ext}"))
    return candidates


def _find_audios() -> list[Path]:
    return sorted(Path(".").glob("test*.wav"))


async def main(case: str = "all_cases") -> None:

    # ── Text only ────────────────────────────────────────────────
    if case in ("text", "all_cases"):
        await run(
            "Text only — dest only (auto pickup)",
            text_input="Take me to Burj Khalifa",
        )

    # ── Multi-stop text ──────────────────────────────────────────
    if case in ("multi", "all_cases"):
        await run(
            "Multi-stop text",
            text_input="Pick me up from Burj Khalifa, stop at City Walk, then drop me at Palm Jumeirah",
        )

    # ── Favorite places ──────────────────────────────────────────
    if case in ("fav_places", "all_cases"):
        await run(
            "Favorite places — 'take me to Work'",
            text_input="Take me to Work",
            favorite_places=["Home", "My work center", "Gym"],
        )
        await run(
            "Favorite places — pickup from favorite",
            text_input="Pick me up from Home and drop at Gym",
            favorite_places=["Home", "Work", "Gym"],
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
                {"text_input": "pick me up from Burj Khalifa"},
                {"text_input": "Yyldyz Hotel"},
            ],
        )


if __name__ == "__main__":
    case = sys.argv[1] if len(sys.argv) > 1 else "all_cases"
    asyncio.run(main(case))
