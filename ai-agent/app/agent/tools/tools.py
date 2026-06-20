from langchain_core.tools import tool
from app.configs.settings import settings
from app.agent.tools.mcp_client import McpClient

_client = McpClient(settings.mcp_server_url)


@tool
async def resolve_geocode(query: str) -> dict:
    """Resolve a free-text travel query (e.g. 'anything to see in Sydney') to a
    canonical place name and GPS coordinates. Always call this first."""
    return await _client.call("resolve_geocode", {"query": query})


@tool
async def search_places(latitude: float, longitude: float) -> list[dict]:
    """Search for attractions, restaurants, and hotels near the given GPS coordinates.
    Pass the latitude and longitude returned by resolve_geocode."""
    return await _client.call("search_places", {"latitude": latitude, "longitude": longitude})


tools = [resolve_geocode, search_places]
