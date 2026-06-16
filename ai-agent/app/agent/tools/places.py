import httpx
from app.config import settings

_BASE = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"


async def _fetch_places(lat: float, lng: float, place_type: str, category: str, limit: int = 8) -> list[dict]:
    params = {
        "location": f"{lat},{lng}",
        "radius": 5000,
        "type": place_type,
        "rankby": "prominence",
        "key": settings.google_api_key,
    }
    async with httpx.AsyncClient() as client:
        resp = await client.get(_BASE, params=params)
        resp.raise_for_status()
        data = resp.json()

    places = []
    for item in data.get("results", [])[:limit]:
        places.append({
            "name": item.get("name", ""),
            "category": category,
            "address": item.get("vicinity", ""),
            "rating": item.get("rating"),
            "description": "",
            "image_url": None,
            "source_url": None,
        })
    return places


async def get_attractions(lat: float, lng: float) -> list[dict]:
    return await _fetch_places(lat, lng, "tourist_attraction", "attraction")


async def get_restaurants(lat: float, lng: float) -> list[dict]:
    return await _fetch_places(lat, lng, "restaurant", "restaurant")


async def get_hotels(lat: float, lng: float) -> list[dict]:
    return await _fetch_places(lat, lng, "lodging", "hotel", limit=5)
