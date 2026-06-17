import logging
from functools import lru_cache
from app.agent.agent_graph import AgentGraph
from app.services.chat_service import ChatService
from app.services.redis_client import RedisClient


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


@lru_cache(maxsize=1)
def get_graph():
    return AgentGraph().build()


@lru_cache(maxsize=1)
def get_redis():
    return RedisClient().get()


@lru_cache(maxsize=1)
def get_chat_service() -> ChatService:
    return ChatService(
        graph=get_graph(),
        redis=get_redis(),
        logger=get_logger("chat_service"),
    )
