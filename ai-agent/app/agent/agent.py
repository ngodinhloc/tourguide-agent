from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage
from app.agent.contracts.agent_interface import AgentState
from app.agent.tools.geocoding import geocode_location
from app.agent.tools.places import search_places
from app.configs.settings import settings


class Agent:
    _SYSTEM = """You are an enthusiastic and knowledgeable travel guide.

When given a travel query:
1. Call geocode_location to resolve the destination to a canonical name and GPS coordinates.
2. Call search_places with the returned latitude and longitude to find nearby venues.
3. Write a comprehensive 2-3 paragraph travel narrative about the destination based on the venues found.

Write the narrative as natural prose. Do not call any more tools after writing it."""

    def __init__(self):
        self._llm = ChatAnthropic(
            model="claude-sonnet-4-6",
            api_key=settings.anthropic_api_key,
            max_tokens=8192,
        ).bind_tools([geocode_location, search_places])

    async def invoke(self, state: AgentState) -> dict:
        messages = state["messages"]
        if not any(isinstance(m, SystemMessage) for m in messages):
            messages = [SystemMessage(content=self._SYSTEM)] + list(messages)
        response = await self._llm.ainvoke(messages)
        return {"messages": [response]}
