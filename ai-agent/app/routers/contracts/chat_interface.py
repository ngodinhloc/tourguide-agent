from enum import Enum
from datetime import datetime
from typing import Optional
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


class ChatMessage(BaseModel):
    actor: ChatActor
    text: str
    timestamp: datetime
    agentStatus: Optional[AgentStatus] = None


class ChatResult(BaseModel):
    location: str
    narrative: str
    places: list[dict] = []


class ChatInterface(BaseModel):
    id: str
    title: Optional[str] = None
    content: list[ChatMessage] = []
    status: ChatStatus
    agentStatus: Optional[AgentStatus] = None
    result: Optional[ChatResult] = None
