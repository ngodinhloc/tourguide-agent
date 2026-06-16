from langgraph.graph import StateGraph, START, END
from app.agent.state import TourState
from app.agent.nodes.planner import planner_node
from app.agent.nodes.researcher import researcher_node
from app.agent.nodes.synthesizer import synthesizer_node


def _should_continue(state: TourState) -> str:
    return "end" if state.get("error") else "researcher"


def build_graph():
    graph = StateGraph(TourState)

    graph.add_node("planner", planner_node)
    graph.add_node("researcher", researcher_node)
    graph.add_node("synthesizer", synthesizer_node)

    graph.add_edge(START, "planner")
    graph.add_conditional_edges("planner", _should_continue, {"researcher": "researcher", "end": END})
    graph.add_edge("researcher", "synthesizer")
    graph.add_edge("synthesizer", END)

    return graph.compile()
