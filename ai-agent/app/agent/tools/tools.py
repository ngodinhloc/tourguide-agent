from langchain_core.tools import tool
from app.configs.settings import settings
from app.agent.tools.mcp_client import McpClient

_client = McpClient(settings.mcp_server_url)


@tool
async def resolve_geocode(query: str) -> dict:
    """Resolve a free-text travel query to a canonical place name and GPS coordinates.
    Only call this when the destination is not already known from the conversation history."""
    return await _client.call("resolve_geocode", {"query": query})


@tool
async def search_places(latitude: float, longitude: float) -> list[dict]:
    """Search for attractions, restaurants, and hotels near the given GPS coordinates.
    Only call this when place data for the destination is not already present in the conversation history."""
    return await _client.call("search_places", {"latitude": latitude, "longitude": longitude})


tools = [resolve_geocode, search_places]
