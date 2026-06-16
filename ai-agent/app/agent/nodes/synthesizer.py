import json
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage
from app.agent.state import TourState, Place
from app.config import settings


_llm = ChatAnthropic(
    model="claude-sonnet-4-6",
    api_key=settings.anthropic_api_key,
    max_tokens=8192,
)


def _format_places_for_prompt(places: list[dict]) -> str:
    lines = []
    for p in places:
        lines.append(f"- {p['name']} ({p['category']}, rating: {p.get('rating', 'N/A')}): {p.get('description', '')}")
    return "\n".join(lines)


async def synthesizer_node(state: TourState) -> dict:
    location = state["location_name"]
    all_places = state["attractions"] + state["restaurants"]
    places_text = _format_places_for_prompt(all_places)

    prompt = f"""You are an enthusiastic and knowledgeable travel guide.

Location: {location}

Available places and venues:
{places_text}

Your tasks:
1. Write an engaging 2-3 paragraph travel narrative about {location} that highlights why it's a great destination.
2. Return a JSON array of the top 15 places (mix of attractions, restaurants, and hotels) with enriched descriptions.

Respond in this exact JSON format:
{{
  "narrative": "<2-3 paragraph narrative here>",
  "places": [
    {{
      "name": "<name>",
      "category": "<attraction|restaurant|hotel>",
      "address": "<address>",
      "rating": <number or null>,
      "description": "<1-2 sentence engaging description>"
    }}
  ]
}}

Only return valid JSON, no other text."""

    response = await _llm.ainvoke([HumanMessage(content=prompt)])
    content = response.content.strip()

    # Strip markdown code fences if present
    if content.startswith("```"):
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]
        content = content.strip()

    data = json.loads(content)
    narrative = data.get("narrative", "")

    # Merge LLM descriptions back with original image/source urls
    place_lookup = {p["name"]: p for p in all_places}
    enriched_places: list[Place] = []
    for p in data.get("places", []):
        original = place_lookup.get(p["name"], {})
        enriched_places.append({
            "name": p["name"],
            "category": p.get("category", original.get("category", "attraction")),
            "address": p.get("address", original.get("address", "")),
            "rating": p.get("rating") or original.get("rating"),
            "description": p.get("description", ""),
            "image_url": original.get("image_url"),
            "source_url": original.get("source_url"),
        })

    return {"narrative": narrative, "places": enriched_places}
