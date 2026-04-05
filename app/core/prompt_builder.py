import json
from datetime import datetime, timezone

_BASE_PROMPT = """You are Yedu, a taxi booking AI.

Rules:
- No pickup / "my location" / "current location" → USER_LOCATION
- Both points known: short friendly sentence + order JSON. Destination unknown: ask only for it.
- Place names always in English; silently fix misspellings ("dubay"→"Dubai", "برج خليفة"→"Burj Khalifa")
- Second-person only ("your trip", not "my trip")
- Favorite place match (by meaning) → use exact label from list; else use as-is
- Restore/undo/cancel → restore last order from history; if none, no order
- Never ask for address clarification; always include known locations in route
- Images: single → ["USER_LOCATION","<place>"]; multiple → 1st=pickup, last=destination

Scheduled datetime:
- Future time/date mentioned → ISO-8601 string (e.g. "2026-04-05T15:00:00")
- "now" / "ASAP" / no mention → null

Passenger count:
- User states number of people/passengers → integer
- Not mentioned → null"""

_TARIFF_RULES = """
Tariff:
- Match user's preference (by meaning) to one of the available tariff ids → set tariff_id
- Not mentioned → null"""


def build_messages(
    user_content: str | list,
    history: list[dict],
    language: str = "en",
    favorite_places: list[str] | None = None,
    tariffs: list[dict] | None = None,
) -> list[dict]:

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S UTC")
    parts = [_BASE_PROMPT, f"\n\nCurrent datetime: {now_str}"]

    has_tariffs = bool(tariffs)

    if has_tariffs:
        parts.append(_TARIFF_RULES)

    schema: dict = {"route": ["pickup", "destination"], "scheduled_datetime": None}
    if has_tariffs:
        schema["tariff_id"] = None
    schema["passenger_count"] = None
    schema_example = json.dumps(schema, separators=(",", ":"))

    parts.append(
        f"\n\nOutput: plain text message, then <<<ORDER>>> + compact JSON object if route is known."
        f" No markdown.\n\n<message>\n<<<ORDER>>>\n{schema_example}"
    )

    dubai_example = _build_order_example(["USER_LOCATION", "Dubai"], has_tariffs)
    parts.append(
        f'\n\nExamples:\n\n"Take me to Dubai" →\nOn my way to Dubai!\n<<<ORDER>>>\n{dubai_example}'
        '\n"Take me somewhere nice" →\nWhere would you like to go?\n\n'
        '"Cancel" (last order had route ["USER_LOCATION","Dubai"]) →\n'
        "Route cleared. Where would you like to go?"
    )

    if favorite_places:
        places_list = ", ".join(f'"{p}"' for p in favorite_places)
        parts.append(
            f"\n\nClient's favorite places: {places_list}\n"
            "If the user refers to any of them (by meaning) → "
            "use that exact label from the list in the route."
        )

    if has_tariffs:
        tariff_lines = "\n".join(
            '  - id: "{id}", name: "{name}"{desc}'.format(
                id=t.get("id", ""),
                name=t.get("name", t.get("id", "")),
                desc=f', description: "{t["description"]}"' if t.get("description") else "",
            )
            for t in tariffs 
        )
        parts.append(f"\n\nAvailable tariffs:\n{tariff_lines}")

    parts.append(f"\n\nUser's language is: {language}")

    system_prompt = "".join(parts)

    return [
        {"role": "system", "content": system_prompt},
        *history,
        {"role": "user", "content": user_content},
    ]


def _build_order_example(
    route: list[str],
    has_tariffs: bool,
    scheduled_datetime: str | None = None,
    tariff_id: str | None = None,
    passenger_count: int | None = None,
) -> str:
    order: dict = {
        "route": route,
        "scheduled_datetime": scheduled_datetime,
    }
    if has_tariffs:
        order["tariff_id"] = tariff_id
    order["passenger_count"] = passenger_count
    return json.dumps(order, separators=(",", ":"))
