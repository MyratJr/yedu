"""app/models/order.py — OrderDraft, Stop, Location."""
from typing import List, Optional
from pydantic import BaseModel


class Location(BaseModel):
    address:   str
    latitude:  float
    longitude: float


class Stop(BaseModel):
    address:   str
    latitude:  float
    longitude: float


class OrderDraft(BaseModel):
    pickup:      Location
    destination: Location
    stops:       List[Stop] = []
    ride_type:   str = "standard"  
    notes:       Optional[str] = None

    def is_complete(self) -> bool:
        return bool(
            self.pickup.address
            and self.destination.address
            and self.pickup.latitude
            and self.destination.latitude
        )