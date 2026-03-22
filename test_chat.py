import asyncio
import grpc
from app.proto import chat_pb2, chat_pb2_grpc


async def main():
    async with grpc.aio.insecure_channel("localhost:50051") as channel:
        stub = chat_pb2_grpc.ChatServiceStub(channel)

        async def requests():
            yield chat_pb2.ChatRequest(
                session_id="sess-1",
                user_id="user-1",
                text_input="I need a ride from my location to the arkach and then stop to Gulzemin then to mir4",
                language="en",
            )

        print("Sending message...\n")

        async for response in stub.Chat(requests()):
            if response.HasField("text_chunk"):
                print(response.text_chunk.text, end="", flush=True)
            elif response.HasField("order_draft"):
                d = response.order_draft
                print(f"\n\n--- ORDER DRAFT ---")
                print(f"Pickup:      {d.pickup_address} ({d.pickup_lat}, {d.pickup_lng})")
                print(f"Destination: {d.destination_address} ({d.destination_lat}, {d.destination_lng})")
                print(f"Ride type:   {d.ride_type}")
            elif response.HasField("action"):
                print(f"\n--- ACTION: {response.action.type} ---")
            elif response.HasField("error"):
                print(f"\n--- ERROR: {response.error.code} — {response.error.message} ---")

        print("\n\nDone.")


asyncio.run(main())