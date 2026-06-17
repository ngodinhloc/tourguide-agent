from langchain_core.messages import AIMessage
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode
from app.agent.contracts.agent_interface import AgentState
from app.agent.agent import Agent
from app.agent.tools.geocoding import geocode_location
from app.agent.tools.places import search_places


class AgentGraph:
    def build(self):
        travel_agent = Agent()
        tool_node = ToolNode([geocode_location, search_places])

        graph = StateGraph(AgentState)
        graph.add_node("agent", travel_agent.invoke)
        graph.add_node("tools", tool_node)
        graph.add_edge(START, "agent")
        graph.add_conditional_edges("agent", self._should_continue, {"tools": "tools", "end": END})
        graph.add_edge("tools", "agent")
        return graph.compile()

    @staticmethod
    def _should_continue(state: AgentState) -> str:
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and last.tool_calls:
            return "tools"
        return "end"


