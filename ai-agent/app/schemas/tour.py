from typing import Optional
from pydantic import BaseModel


class TourRequest(BaseModel):
    location: str
    preferences: Optional[dict] = None


class PlaceOut(BaseModel):
    name: str
    category: str  # "attraction" | "restaurant" | "hotel"
    address: str
    rating: Optional[float] = None
    description: str
    image_url: Optional[str] = None
    source_url: Optional[str] = None


class TourResponse(BaseModel):
    location: str
    narrative: str
    places: list[PlaceOut]
    error: Optional[str] = None
