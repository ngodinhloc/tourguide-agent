# AI Agent — Agent Instructions

Python FastAPI service that runs a LangGraph pipeline to generate travel guide responses. It reads/writes the `ChatInterface` directly in Redis so the frontend can poll for incremental progress.

## Stack

- **FastAPI** — two routers: `/api/tour` (legacy) and `/api/chat` (primary)
- **LangGraph** — 3-node stateful graph (planner → researcher → synthesizer)
- **LangChain Anthropic** — Claude via `langchain-anthropic`
- **httpx** — async HTTP calls to Google APIs
- **redis[asyncio]** — reads and writes `ChatInterface` in Redis
- **pydantic-settings** — typed config from `.env`

## File structure

```
app/
  main.py                 FastAPI app, CORS, router registration
  config.py               Settings (anthropic_api_key, google_api_key, redis_url, …)
  redis_client.py         Lazy singleton aioredis client (get_redis())
  agent/
    graph.py              build_graph() — compiles the LangGraph StateGraph
    state.py              TourState TypedDict
    nodes/
      planner.py          Geocodes raw_query → location_name, lat, lng
      researcher.py       Parallel Google Places calls (attractions, restaurants, hotels)
      synthesizer.py      Claude LLM → narrative + enriched place descriptions
    tools/
      geocoding.py        Google Geocoding API
      places.py           Google Places API (get_attractions, get_restaurants, get_hotels)
  routers/
    health.py             GET /api/health
    tour.py               POST /api/tour (legacy, single-shot)
    chat.py               POST /api/chat (primary — streams progress to Redis)
  schemas/
    tour.py               TourRequest / TourResponse / PlaceOut
    chat.py               ChatRequest / ChatResponse
    chat_interface.py     Python mirror of the TypeScript ChatInterface contracts
                          ChatInterface, ChatMessage, ChatStatus, AgentStatus, ChatActor
```

## `/api/chat` streaming flow

The endpoint receives `{ conversationId, message }`, then:

1. Loads `ChatInterface` from Redis key `chat:{conversationId}` (written by the NestJS backend)
2. Sets `agentStatus = isThinking`, writes to Redis
3. Streams `graph.astream(initial_state, stream_mode="updates")`:
   - **planner** completes → appends `"Identified location: {name}"` ChatMessage, updates Redis
   - **researcher** completes → appends `"Found N attractions and M restaurants"`, updates Redis
   - **synthesizer** completes → appends the full narrative, sets `agentStatus = hasReplied`, updates Redis
4. Returns `ChatResponse` to the NestJS caller (which ignores it — fire-and-forget)

## ChatInterface Python models (`schemas/chat_interface.py`)

These mirror the TypeScript contracts in the backend exactly. Keep them in sync when modifying either side.

```python
class ChatStatus(str, Enum):  active, stopped
class AgentStatus(str, Enum): is_thinking = "isThinking", has_replied = "hasReplied"
class ChatActor(str, Enum):   user = "User", agent = "Agent"
class ChatMessage(BaseModel): actor, text, timestamp
class ChatInterface(BaseModel): id, title, content, status, agentStatus
```

Serialise with `model.model_dump_json()` — Pydantic v2 outputs ISO timestamps and enum string values automatically.

## Google Places API

`places.py` calls the Nearby Search endpoint for three types: `tourist_attraction`, `restaurant`, `lodging`. All three share `_fetch_places(lat, lng, place_type, category, limit)`.

## Environment

```
ANTHROPIC_API_KEY=
GOOGLE_API_KEY=
REDIS_URL=redis://localhost:6379
CORS_ORIGINS=http://localhost:3000
LANGSMITH_API_KEY=        # optional
LANGSMITH_TRACING=false   # optional
LANGSMITH_PROJECT=tourguide-agent
```

## Dev commands

```bash
pip install .
uvicorn app.main:app --reload --port 8001   # http://localhost:8001
```
