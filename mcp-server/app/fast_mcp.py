from fastmcp import FastMCP
from app.container import container

fast_mcp = FastMCP("Tour Guide MCP Server")


@fast_mcp.tool()
async def resolve_geocode(query: str) -> dict:
    """Resolve a free-text travel query to a canonical place name and GPS coordinates. Always call this first."""
    return await container.geocoding_tool.resolve(query)


@fast_mcp.tool()
async def search_places(latitude: float, longitude: float) -> list[dict]:
    """Search for attractions, restaurants, and hotels near the given GPS coordinates.
    Pass the latitude and longitude returned by resolve_geocode."""
    return await container.places_tool.search(latitude, longitude)
