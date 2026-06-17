from langgraph.graph import MessagesState


class AgentState(MessagesState):
    raw_query: str
