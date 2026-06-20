import json
import logging
from app.services.chat_service import ChatService
from app.events.contracts.chat_interface import ChatEvent, HistoryMessage
from app.events.contracts.consumer_message import ConsumerMessage


class ChatEventHandler:
    def __init__(self, chat_service: ChatService, logger: logging.Logger):
        self._chat_service = chat_service
        self._logger = logger

    async def handle(self, message: ConsumerMessage) -> None:
        try:
            payload = json.loads(message.body)
            event = ChatEvent(
                conversationId=payload["conversationId"],
                message=payload["message"],
                history=[HistoryMessage(**m) for m in payload.get("history", [])],
            )
            self._logger.info(
                "Received event conversationId=%s message=%s history_length=%d",
                event.conversationId,
                event.message,
                len(event.history),
            )
            await self._chat_service.handle(event)
        except Exception:
            self._logger.exception("Failed to process message: %s", message.body)
