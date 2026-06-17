import json
import logging
from datetime import datetime, timezone
from fastapi import HTTPException
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from app.routers.contracts.chat import ChatRequest, ChatResponse
from app.routers.contracts.chat_interface import ChatInterface, ChatMessage, ChatActor, AgentStatus, ChatResult


class ChatService:
    def __init__(self, graph, redis, logger: logging.Logger):
        self._graph = graph
        self._redis = redis
        self._logger = logger

    async def handle(self, request: ChatRequest) -> ChatResponse:
        key = self._redis_key(request.conversationId)

        raw = await self._redis.get(key)
        if not raw:
            raise HTTPException(status_code=404, detail=f"Conversation {request.conversationId} not found")

        chat_obj = ChatInterface.model_validate_json(raw)
        chat_obj.agentStatus = AgentStatus.is_thinking
        await self._redis.set(key, chat_obj.model_dump_json())

        initial_messages = [HumanMessage(content=request.message)]
        all_messages: list = list(initial_messages)
        error: str | None = None

        try:
            async for update in self._graph.astream(
                {"messages": initial_messages, "raw_query": request.message},
                stream_mode="updates",
            ):
                for node_name, node_output in update.items():
                    new_msgs = node_output.get("messages", [])
                    all_messages.extend(new_msgs)

                    if node_name == "agent" and new_msgs:
                        last = new_msgs[-1]
                        if isinstance(last, AIMessage) and last.tool_calls:
                            for tc in last.tool_calls:
                                chat_obj.content.append(
                                    self._make_message(f"Calling tool {tc['name']}", AgentStatus.is_thinking)
                                )

                    await self._redis.set(key, chat_obj.model_dump_json())

        except Exception as e:
            error = str(e)
            self._logger.exception("Graph error for conversation %s", request.conversationId)

        location_name, narrative, places, tool_error = self._extract_results(all_messages, request.message)
        if tool_error and not error:
            error = tool_error

        reply_text = f"Error: {error}" if error else narrative
        chat_obj.result = ChatResult(location=location_name, narrative=narrative, places=places)
        chat_obj.content.append(self._make_message(reply_text, AgentStatus.has_replied))
        chat_obj.agentStatus = AgentStatus.has_replied
        await self._redis.set(key, chat_obj.model_dump_json())

        if error:
            raise HTTPException(status_code=500, detail=error)

        return ChatResponse(
            conversationId=request.conversationId,
            location=location_name,
            narrative=narrative,
            places=places,
        )

    @staticmethod
    def _redis_key(conversation_id: str) -> str:
        return f"chat:{conversation_id}"

    @staticmethod
    def _make_message(text: str, agent_status: AgentStatus) -> ChatMessage:
        return ChatMessage(
            actor=ChatActor.agent,
            text=text,
            timestamp=datetime.now(timezone.utc),
            agentStatus=agent_status,
        )

    @staticmethod
    def _extract_results(messages: list, raw_query: str) -> tuple[str, str, list, str | None]:
        location_name = raw_query
        places: list = []
        narrative = ""
        error: str | None = None

        for msg in messages:
            if isinstance(msg, ToolMessage):
                try:
                    result = json.loads(msg.content)
                    if isinstance(result, dict):
                        if "location_name" in result:
                            location_name = result["location_name"]
                        elif "error" in result:
                            error = result["error"]
                    elif isinstance(result, list):
                        places = result
                except Exception:
                    pass

        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and not getattr(msg, "tool_calls", None):
                narrative = msg.content if isinstance(msg.content, str) else ""
                break

        return location_name, narrative, places, error
