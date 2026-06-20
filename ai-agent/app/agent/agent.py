from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage
from app.agent.contracts.agent_interface import AgentState
from app.agent.tools.tools import tools
from app.configs.settings import settings


class Agent:
    _SYSTEM = """You are an enthusiastic and knowledgeable travel guide.

When given a travel query, follow this decision process:

If the conversation already contains place data for the relevant destination (i.e. a previous reply included a list of venues with names, ratings, and addresses):
- Do NOT call resolve_geocode or search_places again.
- Reuse the existing places from the conversation history.
- Rewrite the narrative to fit the new angle (e.g. "for a weekend", "for families", "best restaurants").

If place data for the destination is not yet available in the conversation:
1. Call resolve_geocode to resolve the destination to a canonical name and GPS coordinates.
2. Call search_places with the returned latitude and longitude to find nearby venues.
3. Write a comprehensive 2-3 paragraph travel narrative based on the venues found.

Write the narrative as natural prose. Do not call any more tools after writing it."""

    def __init__(self):
        self._llm = ChatAnthropic(
            model="claude-sonnet-4-6",
            api_key=settings.anthropic_api_key,
            max_tokens=8192,
        ).bind_tools(tools)

    async def invoke(self, state: AgentState) -> dict:
        messages = state["messages"]
        if not any(isinstance(m, SystemMessage) for m in messages):
            messages = [SystemMessage(content=self._SYSTEM)] + list(messages)
        response = await self._llm.ainvoke(messages)
        return {"messages": [response]}
