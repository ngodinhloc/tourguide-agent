import json
from datetime import datetime, timezone
from fastapi import HTTPException
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from app.routers.contracts.chat_interface import (
    ChatInterface, ChatMessage, ChatActor, AgentStatus, ChatContent,
)


class ChatManager:
    def __init__(self, redis):
        self._redis = redis

    async def load_chat(self, key: str, conversation_id: str) -> ChatInterface:
        """Load the chat object from Redis and mark it as thinking.

        Args:
            key: Redis key for the conversation.
            conversation_id: Used in the 404 error detail if the key is missing.

        Returns:
            The hydrated ChatInterface with agentStatus set to is_thinking.

        Raises:
            HTTPException: 404 if the conversation does not exist in Redis.
        """
        raw = await self._redis.get(key)
        if not raw:
            raise HTTPException(status_code=404, detail=f"Conversation {conversation_id} not found")
        chat_obj = ChatInterface.model_validate_json(raw)
        chat_obj.agentStatus = AgentStatus.is_thinking
        await self._redis.set(key, chat_obj.model_dump_json())
        return chat_obj

    async def save_chat(self, key: str, chat_obj: ChatInterface) -> None:
        """Persist the current chat state to Redis.

        Args:
            key: Redis key for the conversation.
            chat_obj: The chat object to serialize and store.
        """
        await self._redis.set(key, chat_obj.model_dump_json())

    def append_tool_call_message(self, chat_obj: ChatInterface, node_name: str, new_msgs: list) -> None:
        """Append a status message to the chat for each tool invoked by the agent node.

        Args:
            chat_obj: The chat object to mutate.
            node_name: Name of the graph node; only "agent" nodes are processed.
            new_msgs: Messages emitted by the node in the current streaming update.
        """
        if node_name == "agent" and new_msgs:
            last = new_msgs[-1]
            if isinstance(last, AIMessage) and last.tool_calls:
                for tc in last.tool_calls:
                    chat_obj.content.append(
                        self.build_chat_message(f"Calling tool {tc['name']}", AgentStatus.is_thinking)
                    )

    async def append_reply_message(
        self, key: str, chat_obj: ChatInterface, error: str | None,
        location_name: str, narrative: str, places: list,
    ) -> None:
        """Append the final agent reply or error to the chat, mark it as replied, and persist to Redis.

        Args:
            key: Redis key for the conversation.
            chat_obj: The chat object to mutate and persist.
            error: Error string if the agent failed, otherwise None.
            location_name: Resolved location name from the agent.
            narrative: Agent-generated narrative text.
            places: List of places returned by the agent.
        """
        if error:
            chat_obj.content.append(self.build_chat_message(f"Error: {error}", AgentStatus.has_replied))
        else:
            chat_obj.content.append(
                self.build_chat_message(
                    ChatContent(location=location_name, narrative=narrative, places=places),
                    AgentStatus.has_replied,
                )
            )
        chat_obj.agentStatus = AgentStatus.has_replied
        await self._redis.set(key, chat_obj.model_dump_json())

    @staticmethod
    def build_messages(history: list, new_message: str) -> list:
        """Convert conversation history and the new user message into a LangChain message list.

        Args:
            history: Prior chat messages from the request.
            new_message: The latest user message to append.

        Returns:
            A list of HumanMessage and AIMessage objects ready for the agent graph.
        """
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
    def build_chat_message(text: str | ChatContent, agent_status: AgentStatus) -> ChatMessage:
        """Build an agent ChatMessage with the given text and status.

        Args:
            text: A plain string (for status/error messages) or a ChatContent object (for replies).
            agent_status: The agent status to attach to the message.

        Returns:
            A ChatMessage attributed to the agent, timestamped to now (UTC).
        """
        return ChatMessage(
            actor=ChatActor.agent,
            text=text,
            timestamp=datetime.now(timezone.utc),
            agentStatus=agent_status,
        )

    @staticmethod
    def extract_results(messages: list, raw_query: str) -> tuple[str, str, list, str | None]:
        """Parse agent messages to extract the location name, narrative, places, and any tool error.

        Args:
            messages: Full list of messages from the agent graph run.
            raw_query: The original user query, used as the fallback location name.

        Returns:
            A tuple of (location_name, narrative, places, error).
        """
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
