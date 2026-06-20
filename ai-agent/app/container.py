import logging
from functools import cached_property
from app.agent.agent_graph import AgentGraph
from app.configs.settings import settings
from app.events.handlers.chat_event_handler import ChatEventHandler
from app.events.rabbitmq_consumer import RabbitMQConsumer
from app.services.chat_service import ChatService
from app.services.chat_manager import ChatManager
from app.services.redis_client import RedisClient


class Container:
    def logger(self, name: str) -> logging.Logger:
        return logging.getLogger(name)

    @cached_property
    def agent_graph(self):
        return AgentGraph().build()

    @cached_property
    def redis_client(self):
        return RedisClient().get()

    @cached_property
    def chat_manager(self) -> ChatManager:
        return ChatManager(self.redis_client)

    @cached_property
    def chat_service(self) -> ChatService:
        return ChatService(
            agent_graph=self.agent_graph,
            chat_manager=self.chat_manager,
            logger=self.logger("chat_service"),
        )

    @cached_property
    def chat_event_handler(self) -> ChatEventHandler:
        return ChatEventHandler(
            chat_service=self.chat_service,
            logger=self.logger("chat_event_handler"),
        )

    @cached_property
    def rabbitmq_consumer(self) -> RabbitMQConsumer:
        return RabbitMQConsumer(
            rabbitmq_url=settings.rabbitmq_url,
            event_handler=self.chat_event_handler,
            logger=self.logger("rabbitmq_consumer"),
        )


container = Container()
