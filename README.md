# Tour Guide Agent

An AI-powered travel guide that accepts a natural-language location query and returns a curated narrative with attractions, restaurants, and hotels — sourced from Google Places and written by Claude. Supports multi-turn conversations so users can refine queries without starting over.

---

## Screenshots

**Agent streaming tool calls**

![Agent streaming tool calls and loading skeleton](./screenshot_1.png)

**Continue chat**

![Completed travel guide for Cabramatta](./screenshot_2.png)

![screenshot_3](./screenshot_3.png)

![screenshot_4](./screenshot_4.png)

![screenshot_5](./screenshot_5.png)

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  Browser                                                     │
│  Next.js frontend  (port 3000)                               │
│  · Search bar, streaming tool-call log, results panel        │
│  · Multi-turn chat with completed-turn history               │
│  · Sidebar with conversation history                         │
└────────────────────────┬─────────────────────────────────────┘
                         │ HTTP  /api/*  (Next.js proxy)
┌────────────────────────▼─────────────────────────────────────┐
│  Backend  (NestJS · port 8000)                               │
│  · REST chat API                                             │
│  · PostgreSQL  — persists conversations as ChatMessage[]     │
│  · Redis       — live chat state during processing           │
│  · Fires async POST to AI Agent (fire-and-forget)            │
└──────────┬───────────────────────────┬───────────────────────┘
           │ async POST /api/chat       │ read / write
           │                           │
┌──────────▼───────────────┐   ┌───────▼────────────┐
│  AI Agent                │   │  Redis             │
│  FastAPI · port 8001     │──▶│  key: chat:{uuid}  │
│  LangGraph ReAct loop    │   └────────────────────┘
│  agent ⇄ tools           │
└──────────────────────────┘
```

---

## Services

### Frontend — Next.js (port 3000)

- Search bar that submits a free-text location query
- Polls `GET /api/chat/{id}` every 2 seconds while the agent is thinking
- Streams tool-call progress messages (`Calling tool geocode_location`, etc.) live in a styled code block with timestamps
- Displays a pulsing `Thinking...` indicator when the agent is processing but has not yet announced a new tool
- Renders each agent reply by inspecting `ChatMessage.type`:
  - `"text"` → display as-is (tool call logs, error messages)
  - `"json"` → parse `text` as `{ location, narrative, places }` and render the full results panel
- Multi-turn UI: completed turns are preserved on screen; each turn shows its own tool-call log and results panel
- `splitTurns` reconstructs all historical turns from a flat `ChatMessage[]` when loading a saved conversation
- Left sidebar with collapsible chat history; clicking an item loads and reconstructs all turns
- All `/api/*` requests are proxied to the backend — the browser never talks to the backend directly

### Backend — NestJS (port 8000)

Orchestrates the chat lifecycle. Key responsibilities:

| Concern | Detail |
|---------|--------|
| **Persistence** | TypeORM + PostgreSQL. Each conversation row has a `jsonb` content column storing a flat `ChatMessage[]` array. |
| **Live state** | Redis key `chat:{uuid}` holds the in-progress `ChatInterface` (content, agentStatus). Deleted after the conversation stops. |
| **AI dispatch** | `POST /api/chat` to the AI Agent is fire-and-forget — Backend returns immediately while the agent works in the background. |
| **Multi-turn** | `POST /api/chat/:id/cont` appends the new user message to the full message history (from Redis or DB) before calling the agent. |
| **Polling** | `GET /api/chat/:id` reads Redis first; falls back to PostgreSQL for completed conversations. Persists to DB (fire-and-forget) when `agentStatus === hasReplied` is detected. |

**Endpoints:**

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/chat/new` | Create conversation in PostgreSQL + Redis, call AI Agent, return `{ id }` |
| `POST` | `/api/chat/:id/cont` | Append user message to history, call AI Agent, return `{ accepted: true }` |
| `GET` | `/api/chat/history` | Return all conversations ordered by creation date (id, title, createdAt) |
| `GET` | `/api/chat/:id` | Return live `ChatInterface` from Redis, or persisted version from PostgreSQL |
| `POST` | `/api/chat/:id/stop` | Persist final `ChatMessage[]` to PostgreSQL, delete Redis key, mark conversation stopped |
| `GET` | `/api/health` | Health check |

### AI Agent — FastAPI + LangGraph (port 8001)

Runs a LangGraph ReAct agent triggered by a single `POST /api/chat` from the backend. The LLM drives the execution — it decides which tools to call, in what order, and when to stop.

**ReAct loop:**

```
agent node  →  reads messages, calls LLM with tools bound
     │
     ├── LLM returns tool_calls  →  tools node executes them  →  back to agent
     │
     └── LLM returns narrative (no tool_calls)  →  END
```

**Multi-turn context:** The request carries the full conversation `history`. `ChatService._build_messages` reconstructs it as LangChain messages — user turns become `HumanMessage`, completed agent replies become `AIMessage` — so the LLM reads the full dialogue before responding.

**Reply encoding:** The final `hasReplied` message uses `type: "json"` with `text = json.dumps({ location, narrative, places })`. All other messages use `type: "text"`. The frontend uses the `type` field to decide how to render each message.

**Tools:**

| Tool | Responsibility | API used |
|------|---------------|----------|
| `geocode_location` | Resolves free-text query to canonical place name + GPS coordinates | Google Geocoding API |
| `search_places` | Fetches nearby attractions, restaurants, and hotels | Google Places API |

**Module structure:**

```
app/
├── agent/
│   ├── contracts/agent_interface.py   — AgentState (extends MessagesState)
│   ├── tools/
│   │   ├── geocoding.py               — GeocodingTool class + @tool geocode_location
│   │   └── places.py                  — PlacesTool class + @tool search_places
│   ├── agent.py                       — TravelAgent class (LLM + system prompt)
│   └── agent_graph.py                 — AgentGraph class (ReAct graph compilation)
├── configs/settings.py                — Settings (Pydantic BaseSettings)
├── di.py                              — Dependency injection (get_graph, get_redis, get_chat_service)
├── main.py                            — FastAPI app, middleware, router registration
├── routers/
│   ├── contracts/
│   │   ├── chat.py                    — ChatRequest (includes history), ChatResponse schemas
│   │   └── chat_interface.py          — ChatInterface, ChatMessage, AgentStatus types
│   ├── chat_router.py                 — POST /api/chat (thin — delegates to ChatService)
│   └── health_router.py               — GET /api/health
└── services/
    ├── chat_service.py                — ChatService (graph execution, Redis streaming)
    └── redis_client.py                — RedisClient class
```

**Endpoints:**

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/chat` | Run the ReAct agent for a conversation (new or continued) |
| `GET` | `/api/health` | Health check |

### PostgreSQL (port 5432)

Stores every conversation permanently. Schema (auto-created by TypeORM in dev):

```
conversations
  uuid        uuid  PRIMARY KEY
  title       varchar(500)
  content     jsonb          — flat ChatMessage[] array
  created_at  timestamptz
  updated_at  timestamptz
```

The `content` column stores the flat `ChatMessage[]` array directly. Each element has `actor`, `text`, `timestamp`, and `agentStatus`. The `text` field is either a plain string (tool call announcements) or a `ChatContent` object (the final structured reply) — stored as native JSON, no embedded JSON strings.

**Sample `content` column value:**

```json
[
  {
    "actor": "User",
    "text": "tell me about Sydney",
    "timestamp": "2026-06-18T00:54:52.046000Z",
    "agentStatus": null
  },
  {
    "actor": "Agent",
    "text": "Calling tool resolve_geocode",
    "timestamp": "2026-06-18T00:54:54.034561Z",
    "agentStatus": "isThinking"
  },
  {
    "actor": "Agent",
    "text": "Calling tool search_places",
    "timestamp": "2026-06-18T00:54:56.798732Z",
    "agentStatus": "isThinking"
  },
  {
    "actor": "Agent",
    "text": {
      "location": "Sydney NSW, Australia",
      "narrative": "Sydney is one of the world's most breathtaking cities...",
      "places": [
        {
          "name": "Sydney Opera House",
          "category": "attraction",
          "address": "Bennelong Point, Sydney",
          "rating": 4.8,
          "description": "",
          "image_url": null,
          "source_url": null
        },
        {
          "name": "Four Seasons Hotel Sydney",
          "category": "hotel",
          "address": "199 George Street, The Rocks",
          "rating": 4.5,
          "description": "",
          "image_url": null,
          "source_url": null
        }
      ]
    },
    "timestamp": "2026-06-18T00:55:10.823519Z",
    "agentStatus": "hasReplied"
  }
]
```

### Redis (internal, no host port)

Ephemeral cache for live conversations. Each key `chat:{uuid}` holds the full `ChatInterface` as JSON. Written by both the Backend and the AI Agent; deleted by Backend on `stopChat`.

---

## Chat workflow

### New conversation

```
User types query and submits
        │
        ▼
POST /api/chat/new  →  Backend
  · Creates PostgreSQL row (content = [userMessage])
  · Writes ChatInterface to Redis  (agentStatus: isThinking)
  · Fires async POST /api/chat to AI Agent
  · Returns { id }
        │
        ▼
AI Agent receives request
  · Builds LangChain messages from history
  · LLM decides to call geocode_location
  · Writes "Calling tool geocode_location" (type:text) to Redis
        │
        ▼
[tools node]  — geocode_location resolves location to GPS coords
  · LLM decides to call search_places
  · Writes "Calling tool search_places" (type:text) to Redis
        │
        ▼
[tools node]  — search_places fetches attractions, restaurants, hotels
  · LLM writes travel narrative (no more tool calls)
  · Writes final ChatMessage  (type:json, agentStatus: hasReplied)
    text = JSON.stringify({ location, narrative, places })
  · Sets ChatInterface.agentStatus = hasReplied in Redis
        │
        ▼
Frontend detects agentStatus === "hasReplied" on next poll
  · Reads finalMsg.type === "json" → JSON.parse(finalMsg.text) → renders ResultsPanel
  · Calls POST /api/chat/:id/stop
        │
        ▼
Backend stopChat
  · Persists ChatMessage[] to PostgreSQL content column
  · Deletes Redis key
  · Sets status: isStopped
        │
        ▼
Sidebar refreshes history list  (chat-completed event)
```

### Continued conversation

```
User types follow-up in the same chat
        │
        ▼
POST /api/chat/:id/cont  →  Backend
  · Reads full history from Redis (or DB if Redis key gone)
  · Appends new user ChatMessage to content array
  · Writes updated ChatInterface to Redis
  · Fires async POST /api/chat to AI Agent (with full history)
  · Returns { accepted: true }
        │
        ▼
AI Agent receives request with conversation history
  · _build_messages reconstructs prior turns as HumanMessage / AIMessage
  · LLM has full context — responds to the follow-up
  · Appends new tool-call and reply messages to Redis
        │
        ▼
Frontend (schedulePoll)
  · agentMessageOffsetRef tracks how many agent messages existed before this turn
  · Only new messages from this turn are rendered as the "current turn"
  · On hasReplied: saves current turn to completedTurns state, renders new ResultsPanel
```

---

## Local URLs

| Service | URL | Notes |
|---------|-----|-------|
| Frontend | http://localhost:3000 | Main app |
| Backend API | http://localhost:8000 | NestJS REST API |
| AI Agent API | http://localhost:8001 | FastAPI (internal port is 8000) |
| PostgreSQL | `localhost:5432` | User `tourguide`, password `tourguide`, database `tourguide` |
| Redis | internal only | Accessible inside Docker network as `redis:6379` |

---

## Quick start

```bash
# 1. Fill in API keys
cp ai-agent/.env.example ai-agent/.env
# edit ai-agent/.env — set ANTHROPIC_API_KEY and GOOGLE_API_KEY

# 2. Start all services
docker-compose up --build
```

Open [http://localhost:3000](http://localhost:3000).

### Required API keys

| Key | Service | Where to get |
|-----|---------|-------------|
| `ANTHROPIC_API_KEY` | AI Agent | [console.anthropic.com](https://console.anthropic.com) |
| `GOOGLE_API_KEY` | AI Agent | Google Cloud Console — enable **Geocoding API** and **Places API** |

---

## Data flow types

```
AgentStatus:  isThinking | hasReplied
ChatStatus:   isActive   | isStopped
ChatActor:    User       | Agent

ChatPlace {
  name:        string
  category:    "attraction" | "restaurant" | "hotel"
  address:     string
  rating:      number | null
  description: string
  image_url:   string | null
  source_url:  string | null
}

ChatContent {
  location:  string
  narrative: string
  places:    ChatPlace[]
}

ChatMessage {
  actor:       ChatActor
  text:        string | ChatContent   // string for tool calls/errors, ChatContent for final reply
  timestamp:   datetime
  agentStatus: AgentStatus | null
}

ChatInterface {
  id:          uuid
  title:       string
  content:     ChatMessage[]
  status:      ChatStatus
  agentStatus: AgentStatus
}
```
