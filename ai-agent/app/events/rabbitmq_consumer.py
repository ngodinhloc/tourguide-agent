import logging
import aio_pika
from app.events.handlers.chat_event_handler import ChatEventHandler

QUEUE = "tour-guide.chat"


class RabbitMQConsumer:
    def __init__(self, rabbitmq_url: str, event_handler: ChatEventHandler, logger: logging.Logger):
        self._url = rabbitmq_url
        self._event_handler = event_handler
        self._logger = logger

    async def start(self) -> None:
        connection = await aio_pika.connect_robust(self._url)
        channel = await connection.channel()
        await channel.set_qos(prefetch_count=1)
        queue = await channel.declare_queue(QUEUE, durable=True)

        self._logger.info("RabbitMQ consumer started, listening on queue: %s", QUEUE)

        async with queue.iterator() as messages:
            async for message in messages:
                async with message.process():
                    await self._event_handler.handle(message)
