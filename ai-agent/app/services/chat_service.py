import json
import logging
from datetime import datetime, timezone
from fastapi import HTTPException
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from app.routers.contracts.chat_interface import (
    ChatInterface, ChatMessage, ChatActor, AgentStatus, ChatContent,
    ChatRequest, ChatResponse,
)


class ChatService:
    def __init__(self, graph, redis, logger: logging.Logger):
        self._graph = graph
        self._redis = redis
        self._logger = logger

    async def handle(self, request: ChatRequest) -> ChatResponse:
        key = self._redis_key(request.conversationId)
        chat_obj = await self._load_chat(key, request.conversationId)

        initial_messages = self._build_messages(request.history, request.message)
        all_messages, error = await self._stream_graph(key, chat_obj, initial_messages, request.message)

        location_name, narrative, places, tool_error = self._extract_results(all_messages, request.message)
        if tool_error and not error:
            error = tool_error

        await self._append_reply(key, chat_obj, error, location_name, narrative, places)

        if error:
            raise HTTPException(status_code=500, detail=error)

        return ChatResponse(
            conversationId=request.conversationId,
            location=location_name,
            narrative=narrative,
            places=places,
        )

    async def _load_chat(self, key: str, conversation_id: str) -> ChatInterface:
        raw = await self._redis.get(key)
        if not raw:
            raise HTTPException(status_code=404, detail=f"Conversation {conversation_id} not found")
        chat_obj = ChatInterface.model_validate_json(raw)
        chat_obj.agentStatus = AgentStatus.is_thinking
        await self._redis.set(key, chat_obj.model_dump_json())
        return chat_obj

    async def _stream_graph(
        self, key: str, chat_obj: ChatInterface, initial_messages: list, raw_query: str
    ) -> tuple[list, str | None]:
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
                    self._append_tool_calls(chat_obj, node_name, new_msgs)
                    await self._redis.set(key, chat_obj.model_dump_json())
        except Exception as e:
            error = str(e)
            self._logger.exception("Graph error for conversation %s", key)
        return all_messages, error

    def _append_tool_calls(self, chat_obj: ChatInterface, node_name: str, new_msgs: list) -> None:
        if node_name == "agent" and new_msgs:
            last = new_msgs[-1]
            if isinstance(last, AIMessage) and last.tool_calls:
                for tc in last.tool_calls:
                    chat_obj.content.append(
                        self._build_chat_message(f"Calling tool {tc['name']}", AgentStatus.is_thinking)
                    )

    async def _append_reply(
        self, key: str, chat_obj: ChatInterface, error: str | None,
        location_name: str, narrative: str, places: list,
    ) -> None:
        if error:
            chat_obj.content.append(self._build_chat_message(f"Error: {error}", AgentStatus.has_replied))
        else:
            chat_obj.content.append(
                self._build_chat_message(
                    ChatContent(location=location_name, narrative=narrative, places=places),
                    AgentStatus.has_replied,
                )
            )
        chat_obj.agentStatus = AgentStatus.has_replied
        await self._redis.set(key, chat_obj.model_dump_json())

    @staticmethod
    def _build_messages(history: list, new_message: str) -> list:
        messages = []
        for msg in history:
            if msg.actor == "User":
                messages.append(HumanMessage(content=msg.text if isinstance(msg.text, str) else ""))
            elif msg.actor == "Agent" and msg.agentStatus == "hasReplied":
                text = msg.text.get("narrative", "") if isinstance(msg.text, dict) else msg.text
                messages.append(AIMessage(content=text))
        messages.append(HumanMessage(content=new_message))
        return messages

    @staticmethod
    def _redis_key(conversation_id: str) -> str:
        return f"chat:{conversation_id}"

    @staticmethod
    def _build_chat_message(text: str | ChatContent, agent_status: AgentStatus) -> ChatMessage:
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
