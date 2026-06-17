from enum import Enum
from datetime import datetime
from typing import Literal, Optional
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


class ChatResult(BaseModel):
    location: str
    narrative: str
    places: list[dict] = []


class ChatMessage(BaseModel):
    actor: ChatActor
    text: str
    timestamp: datetime
    agentStatus: Optional[AgentStatus] = None
    type: Literal["text", "json"] = "text"


class ChatInterface(BaseModel):
    id: str
    title: Optional[str] = None
    content: list[ChatMessage] = []
    status: ChatStatus
    agentStatus: Optional[AgentStatus] = None
