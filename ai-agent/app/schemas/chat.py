from typing import Optional
from pydantic import BaseModel
from app.schemas.tour import PlaceOut


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
