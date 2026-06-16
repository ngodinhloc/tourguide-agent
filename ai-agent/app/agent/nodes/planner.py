from app.agent.state import TourState
from app.agent.tools.geocoding import geocode


async def planner_node(state: TourState) -> dict:
    try:
        location_name, lat, lng = await geocode(state["raw_query"])
        return {"location_name": location_name, "latitude": lat, "longitude": lng, "error": None}
    except ValueError as e:
        return {"location_name": state["raw_query"], "latitude": 0.0, "longitude": 0.0, "error": str(e)}
