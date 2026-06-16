from fastapi import APIRouter, HTTPException
from app.schemas.tour import TourRequest, TourResponse
from app.agent.graph import build_graph

router = APIRouter()
_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


@router.post("/tour", response_model=TourResponse)
async def tour(request: TourRequest):
    try:
        graph = get_graph()
        initial_state = {
            "raw_query": request.location,
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
        final_state = await graph.ainvoke(initial_state)
        if final_state.get("error"):
            return TourResponse(
                location=final_state.get("location_name", request.location),
                narrative="",
                places=[],
                error=final_state["error"],
            )
        return TourResponse(
            location=final_state["location_name"],
            narrative=final_state["narrative"],
            places=final_state["places"],
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
