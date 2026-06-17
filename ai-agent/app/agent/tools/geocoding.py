import httpx
from langchain_core.tools import tool
from app.configs.settings import settings


class GeocodingTool:
    _URL = "https://maps.googleapis.com/maps/api/geocode/json"

    async def geocode(self, query: str) -> tuple[str, float, float]:
        async with httpx.AsyncClient() as client:
            resp = await client.get(self._URL, params={"address": query, "key": settings.google_api_key})
            resp.raise_for_status()
            data = resp.json()

        status = data.get("status")
        if status != "OK" or not data.get("results"):
            raise ValueError(f"Geocoding failed for {query!r}: {status} — {data.get('error_message', 'no details')}")

        result = data["results"][0]
        lat = result["geometry"]["location"]["lat"]
        lng = result["geometry"]["location"]["lng"]
        return result["formatted_address"], lat, lng

    async def resolve(self, query: str) -> dict:
        try:
            name, lat, lng = await self.geocode(query)
            return {"location_name": name, "latitude": lat, "longitude": lng}
        except ValueError as e:
            return {"error": str(e)}


_geocoding_tool = GeocodingTool()


@tool
async def geocode_location(query: str) -> dict:
    """Resolve a free-text travel query (e.g. 'anything to see in Sydney') to a
    canonical place name and GPS coordinates. Always call this first."""
    return await _geocoding_tool.resolve(query)
