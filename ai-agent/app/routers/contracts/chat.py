from typing import Optional
from pydantic import BaseModel


class PlaceOut(BaseModel):
    name: str
    category: str
    address: str
    rating: Optional[float] = None
    description: str
    image_url: Optional[str] = None
    source_url: Optional[str] = None


class ChatRequest(BaseModel):
    conversationId: str
    message: str
    preferences: Optional[dict] = None


class ChatResponse(BaseModel):
    conversationId: str
    location: str
    narrative: str
    places: list[PlaceOut]
    error: Optional[str] = None
