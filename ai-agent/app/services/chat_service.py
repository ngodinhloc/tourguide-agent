import logging
from fastapi import HTTPException
from app.agent.agent_graph import AgentGraph
from app.events.contracts.chat_interface import ChatEvent, ChatReply
from app.services.chat_manager import ChatManager
from app.services.redis_helper import RedisHelper


class ChatService:
    def __init__(self, agent_graph: AgentGraph, chat_manager: ChatManager, logger: logging.Logger):
        self._graph = agent_graph
        self._logger = logger
        self._message_manager = chat_manager

    async def handle(self, request: ChatEvent) -> ChatReply:
        """Process a chat request end-to-end: load state, run the agent graph, and return the reply.

        Args:
            request: The incoming chat request containing the conversation ID, history, and message.

        Returns:
            A ChatResponse with the resolved location, narrative, and places.

        Raises:
            HTTPException: 404 if the conversation is not found; 500 if the agent graph fails.
        """
        key = RedisHelper.chat_key(request.conversationId)
        chat_obj = await self._message_manager.load_chat(key, request.conversationId)

        initial_messages = self._message_manager.build_messages(request.history, request.message)
        all_messages, error = await self._stream_graph(key, chat_obj, initial_messages, request.message)

        location_name, narrative, places, tool_error = self._message_manager.extract_results(all_messages, request.message)
        if tool_error and not error:
            error = tool_error

        # When the LLM skips tool calls (e.g. follow-up refining an existing result),
        # reuse places and location from the most recent completed turn in history.
        if not places:
            for msg in reversed(request.history):
                if msg.actor == "Agent" and msg.agentStatus == "hasReplied" and isinstance(msg.text, dict):
                    places = msg.text.get("places", [])
                    location_name = msg.text.get("location", location_name)
                    break

        await self._message_manager.append_reply_message(key, chat_obj, error, location_name, narrative, places)

        if error:
            raise HTTPException(status_code=500, detail=error)

        return ChatReply(
            conversationId=request.conversationId,
            location=location_name,
            narrative=narrative,
            places=places,
        )

    async def _stream_graph(
        self, key: str, chat_obj, initial_messages: list, raw_query: str
    ) -> tuple[list, str | None]:
        """Stream agent graph updates, appending tool-call messages and persisting state after each node.

        Args:
            key: Redis key used to persist intermediate chat state.
            chat_obj: The chat object mutated during streaming.
            initial_messages: LangChain messages passed as the graph input.
            raw_query: The original user query passed alongside messages.

        Returns:
            A tuple of (all_messages, error) where error is None on success.
        """
        all_messages = list(initial_messages)
        error: str | None = None
        try:
            async for update in self._graph.astream(
                {"messages": initial_messages, "raw_query": raw_query},
                stream_mode="updates",
            ):
                for node_name, node_output in update.items():
                    new_msgs = node_output.get("messages", [])
                    all_messages.extend(new_msgs)
                    self._message_manager.append_tool_call_message(chat_obj, node_name, new_msgs)
                    await self._message_manager.save_chat(key, chat_obj)
        except Exception as e:
            error = str(e)
            self._logger.exception("Graph error for conversation %s", key)
        return all_messages, error
