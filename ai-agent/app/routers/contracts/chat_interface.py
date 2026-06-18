from enum import Enum
from datetime import datetime
from typing import Optional, Union
from pydantic import BaseModel


class ChatStatus(str, Enum):
    is_active = "isActive"
    is_stopped = "isStopped"


class AgentStatus(str, Enum):
    is_thinking = "isThinking"
    has_replied = "hasReplied"


class ChatActor(str, Enum):
    user = "User"
    agent = "Agent"


class ChatPlace(BaseModel):
    name: str
    category: str
    address: str
    rating: Optional[float] = None
    description: str = ""
    image_url: Optional[str] = None
    source_url: Optional[str] = None


class ChatContent(BaseModel):
    location: str
    narrative: str
    places: list[ChatPlace] = []


class ChatMessage(BaseModel):
    actor: ChatActor
    text: Union[str, ChatContent]
    timestamp: datetime
    agentStatus: Optional[AgentStatus] = None


class ChatInterface(BaseModel):
    id: str
    title: Optional[str] = None
    content: list[ChatMessage] = []
    status: ChatStatus
    agentStatus: Optional[AgentStatus] = None


class HistoryMessage(BaseModel):
    actor: str
    text: Union[str, dict]
    agentStatus: Optional[str] = None


class ChatRequest(BaseModel):
    conversationId: str
    message: str
    history: list[HistoryMessage] = []
    preferences: Optional[dict] = None


class ChatResponse(BaseModel):
    conversationId: str
    location: str
    narrative: str
    places: list[ChatPlace]
    error: Optional[str] = None
