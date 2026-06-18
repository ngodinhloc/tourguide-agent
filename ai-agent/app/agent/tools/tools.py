from langchain_core.tools import tool
from app.agent.tools.geocoding_tool import GeocodingTool
from app.agent.tools.places_tool import PlacesTool


@tool
async def resolve_geocode(query: str) -> dict:
    """Resolve a free-text travel query (e.g. 'anything to see in Sydney') to a
    canonical place name and GPS coordinates. Always call this first."""
    return await GeocodingTool().resolve(query)


@tool
async def search_places(latitude: float, longitude: float) -> list[dict]:
    """Search for attractions, restaurants, and hotels near the given GPS coordinates.
    Pass the latitude and longitude returned by resolve_geocode."""
    return await PlacesTool().search(latitude, longitude)


tools = [resolve_geocode, search_places]
