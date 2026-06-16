import asyncio
from app.agent.state import TourState
from app.agent.tools.places import get_attractions, get_restaurants, get_hotels


async def researcher_node(state: TourState) -> dict:
    lat = state["latitude"]
    lng = state["longitude"]

    attractions, restaurants, hotels = await asyncio.gather(
        get_attractions(lat, lng),
        get_restaurants(lat, lng),
        get_hotels(lat, lng),
    )

    return {
        "attractions": attractions,
        "restaurants": restaurants + hotels,
    }
