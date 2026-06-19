from pydantic import BaseModel
from app.container import container

TOOLS_SCHEMA = [
    {
        "name": "resolve_geocode",
        "description": "Resolve a free-text travel query to a canonical place name and GPS coordinates. Always call this first.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Free-text location query"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_places",
        "description": "Search for attractions, restaurants, and hotels near the given GPS coordinates. Pass the latitude and longitude returned by resolve_geocode.",
        "parameters": {
            "type": "object",
            "properties": {
                "latitude": {"type": "number", "description": "Latitude from resolve_geocode"},
                "longitude": {"type": "number", "description": "Longitude from resolve_geocode"},
            },
            "required": ["latitude", "longitude"],
        },
    },
]

TOOL_DISPATCH = {
    "resolve_geocode": lambda args: container.geocoding_tool.resolve(args["query"]),
    "search_places": lambda args: container.places_tool.search(args["latitude"], args["longitude"]),
}


class ToolCallRequest(BaseModel):
    name: str
    arguments: dict
