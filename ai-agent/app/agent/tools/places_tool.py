import asyncio
import httpx
from app.configs.settings import settings


class PlacesTool:
    _BASE = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"

    async def _fetch(self, lat: float, lng: float, place_type: str, category: str, limit: int = 8) -> list[dict]:
        params = {
            "location": f"{lat},{lng}",
            "radius": 5000,
            "type": place_type,
            "rankby": "prominence",
            "key": settings.google_api_key,
        }
        async with httpx.AsyncClient() as client:
            resp = await client.get(self._BASE, params=params)
            resp.raise_for_status()
            data = resp.json()

        return [
            {
                "name": item.get("name", ""),
                "category": category,
                "address": item.get("vicinity", ""),
                "rating": item.get("rating"),
                "description": "",
                "image_url": None,
                "source_url": None,
            }
            for item in data.get("results", [])[:limit]
        ]

    async def get_attractions(self, lat: float, lng: float) -> list[dict]:
        return await self._fetch(lat, lng, "tourist_attraction", "attraction")

    async def get_restaurants(self, lat: float, lng: float) -> list[dict]:
        return await self._fetch(lat, lng, "restaurant", "restaurant")

    async def get_hotels(self, lat: float, lng: float) -> list[dict]:
        return await self._fetch(lat, lng, "lodging", "hotel", limit=5)

    async def search(self, latitude: float, longitude: float) -> list[dict]:
        attractions, restaurants, hotels = await asyncio.gather(
            self.get_attractions(latitude, longitude),
            self.get_restaurants(latitude, longitude),
            self.get_hotels(latitude, longitude),
        )
        return attractions + restaurants + hotels

