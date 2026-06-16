import logging
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from app.schemas.chat import ChatRequest, ChatResponse
from app.schemas.chat_interface import ChatInterface, ChatMessage, ChatActor, AgentStatus, ChatResult
from app.redis_client import get_redis
from app.routers.tour import get_graph

router = APIRouter()
logger = logging.getLogger(__name__)

# Maps each completed node to the next node that will start immediately after.
_NEXT_NODE: dict[str, str] = {
    "planner": "researcher",
    "researcher": "synthesizer",
}


def _redis_key(conversation_id: str) -> str:
    return f"chat:{conversation_id}"


def _message(text: str, agent_status: AgentStatus) -> ChatMessage:
    return ChatMessage(
        actor=ChatActor.agent,
        text=text,
        timestamp=datetime.now(timezone.utc),
        agentStatus=agent_status,
    )


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    redis = get_redis()
    key = _redis_key(request.conversationId)

    raw = await redis.get(key)
    if not raw:
        raise HTTPException(status_code=404, detail=f"Conversation {request.conversationId} not found")

    chat_obj = ChatInterface.model_validate_json(raw)
    chat_obj.agentStatus = AgentStatus.is_thinking

    # Pre-announce the first node so the UI shows activity immediately.
    chat_obj.content.append(_message("Calling tool planner", AgentStatus.is_thinking))
    await redis.set(key, chat_obj.model_dump_json())

    graph = get_graph()
    initial_state = {
        "raw_query": request.message,
        "preferences": request.preferences or {},
        "location_name": "",
        "latitude": 0.0,
        "longitude": 0.0,
        "attractions": [],
        "restaurants": [],
        "narrative": "",
        "places": [],
        "error": None,
    }

    final_narrative = ""
    final_places = []
    final_location = request.message
    error: str | None = None

    try:
        async for update in graph.astream(initial_state, stream_mode="updates"):
            for node_name, node_output in update.items():
                if node_name == "planner":
                    if node_output.get("error"):
                        error = node_output["error"]
                        logger.error("Planner error for %s: %s", request.conversationId, error)
                    else:
                        final_location = node_output.get("location_name", request.message)
                elif node_name == "synthesizer":
                    final_narrative = node_output.get("narrative", "")
                    final_places = node_output.get("places", [])

                # Pre-announce the next node so the frontend shows progress
                # immediately rather than waiting for the next node to complete.
                next_node = _NEXT_NODE.get(node_name)
                if next_node and not error:
                    chat_obj.content.append(_message(f"Calling tool {next_node}", AgentStatus.is_thinking))

                await redis.set(key, chat_obj.model_dump_json())

    except Exception as e:
        error = str(e)
        logger.exception("Graph error for conversation %s", request.conversationId)

    reply_text = f"Error: {error}" if error else final_narrative
    chat_obj.result = ChatResult(location=final_location, narrative=final_narrative, places=final_places)
    chat_obj.content.append(_message(reply_text, AgentStatus.has_replied))
    chat_obj.agentStatus = AgentStatus.has_replied
    await redis.set(key, chat_obj.model_dump_json())

    if error:
        raise HTTPException(status_code=500, detail=error)

    return ChatResponse(
        conversationId=request.conversationId,
        location=final_location,
        narrative=final_narrative,
        places=final_places,
    )
