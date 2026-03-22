"""tests/test_response_parser.py"""

import pytest
from app.core.response_parser import extract_order_draft, strip_order_draft_tag


SAMPLE = """Sure! I found your locations.
<order_draft>
{
  "pickup":      {"address": "Ashgabat Airport", "latitude": 37.9868, "longitude": 58.3610},
  "destination": {"address": "Yyldyz Hotel",     "latitude": 37.9344, "longitude": 58.3800},
  "stops":       [],
  "ride_type":   "standard",
  "notes":       ""
}
</order_draft>
Shall I confirm this ride?"""


def test_extract_order_draft():
    draft = extract_order_draft(SAMPLE)
    assert draft is not None
    assert draft.pickup.address == "Ashgabat Airport"
    assert draft.destination.address == "Yyldyz Hotel"
    assert draft.ride_type == "standard"
    assert draft.is_complete()


def test_extract_order_draft_missing():
    assert extract_order_draft("No order here.") is None


def test_strip_order_draft_tag():
    result = strip_order_draft_tag(SAMPLE)
    assert "<order_draft>" not in result
    assert "Shall I confirm" in result