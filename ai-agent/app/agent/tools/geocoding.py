import httpx
from app.config import settings


async def geocode(query: str) -> tuple[str, float, float]:
    """Returns (formatted_address, latitude, longitude). Raises ValueError if not found."""
    url = "https://maps.googleapis.com/maps/api/geocode/json"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, params={"address": query, "key": settings.google_api_key})
        resp.raise_for_status()
        data = resp.json()

    status = data.get("status")
    if status != "OK" or not data.get("results"):
        raise ValueError(f"Geocoding failed for {query!r}: {status} — {data.get('error_message', 'no details')}")

    result = data["results"][0]
    formatted = result["formatted_address"]
    lat = result["geometry"]["location"]["lat"]
    lng = result["geometry"]["location"]["lng"]
    return formatted, lat, lng
