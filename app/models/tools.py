"""app/models/tools.py — Tool definitions for LLM function calling."""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_places",
            "description": (
                "Search for a place by name or description and return "
                "its address and coordinates."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Place name or description to search for.",
                    },
                    "language": {
                        "type": "string",
                        "enum": ["en", "ar"],
                        "description": "Language for results.",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "geocode_address",
            "description": "Convert a street address to latitude/longitude.",
            "parameters": {
                "type": "object",
                "properties": {
                    "address": {"type": "string"},
                },
                "required": ["address"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reverse_geocode",
            "description": "Convert latitude/longitude to a human-readable address.",
            "parameters": {
                "type": "object",
                "properties": {
                    "latitude":  {"type": "number"},
                    "longitude": {"type": "number"},
                },
                "required": ["latitude", "longitude"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "request_user_location",
            "description": (
                "Ask the client app to provide the user's current GPS location. "
                "Call this when the user says 'pick me up here' or similar."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
]