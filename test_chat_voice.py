import asyncio
import grpc
from app.proto import chat_pb2, chat_pb2_grpc


async def main():
    # Read your audio file
    audio_path = "client_voice.wav"   # put your audio file here
    with open(audio_path, "rb") as f:
        audio_bytes = f.read()

    async with grpc.aio.insecure_channel("localhost:50051") as channel:
        stub = chat_pb2_grpc.ChatServiceStub(channel)

        async def requests():
            yield chat_pb2.ChatRequest(
                session_id="sess-voice-1",
                user_id="user-1",
                audio_input=audio_bytes,   # ← send as bytes
                language="en",
            )

        print("Sending voice message...\n")

        async for response in stub.Chat(requests()):
            if response.HasField("text_chunk"):
                print(response.text_chunk.text, end="", flush=True)
            elif response.HasField("order_draft"):
                d = response.order_draft
                print(f"\n\n--- ORDER DRAFT ---")
                print(f"Pickup:      {d.pickup_address}")
                print(f"Destination: {d.destination_address}")
                print(f"Ride type:   {d.ride_type}")
            elif response.HasField("action"):
                print(f"\n--- ACTION: {response.action.type} ---")
            elif response.HasField("error"):
                print(f"\n--- ERROR: {response.error.code} — {response.error.message} ---")

        print("\n\nDone.")


asyncio.run(main())