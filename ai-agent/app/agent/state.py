from typing import Optional, TypedDict


class Place(TypedDict):
    name: str
    category: str  # "attraction" | "restaurant" | "hotel"
    address: str
    rating: Optional[float]
    description: str
    image_url: Optional[str]
    source_url: Optional[str]


class TourState(TypedDict):
    # input
    raw_query: str
    preferences: dict

    # planner outputs
    location_name: str
    latitude: float
    longitude: float

    # researcher outputs
    attractions: list[Place]
    restaurants: list[Place]

    # synthesizer outputs
    narrative: str
    places: list[Place]

    # control
    error: Optional[str]
