import logging
from functools import cached_property
from app.tools.geocoding_tool import GeocodingTool
from app.tools.places_tool import PlacesTool


class Container:
    def logger(self, name: str) -> logging.Logger:
        return logging.getLogger(name)

    @cached_property
    def geocoding_tool(self) -> GeocodingTool:
        return GeocodingTool()

    @cached_property
    def places_tool(self) -> PlacesTool:
        return PlacesTool()


container = Container()
