import logging
from functools import cached_property
from app.agent.agent_graph import AgentGraph
from app.services.chat_service import ChatService
from app.services.redis_client import RedisClient


class Container:
    def logger(self, name: str) -> logging.Logger:
        return logging.getLogger(name)

    @cached_property
    def graph(self):
        return AgentGraph().build()

    @cached_property
    def redis(self):
        return RedisClient().get()

    @cached_property
    def chat_service(self) -> ChatService:
        return ChatService(
            graph=self.graph,
            redis=self.redis,
            logger=self.logger("chat_service"),
        )


container = Container()
