# Tour Guide Agent

An AI-powered travel guide that accepts a natural-language location query and returns a curated narrative with attractions, restaurants, and hotels — sourced from Google Places and written by Claude.

---

## Screenshots

**Agent streaming tool calls**

![Agent streaming tool calls and loading skeleton](./screenshot_1.png)

**Completed travel guide**

![Completed travel guide for Melbourne](./screenshot_2.png)

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  Browser                                                     │
│  Next.js frontend  (port 3000)                               │
│  · Search bar, streaming tool-call log, results panel        │
│  · Sidebar with chat history                                 │
└────────────────────────┬─────────────────────────────────────┘
                         │ HTTP  /api/*  (Next.js proxy)
┌────────────────────────▼─────────────────────────────────────┐
│  Backend  (NestJS · port 8000)                               │
│  · REST chat API                                             │
│  · PostgreSQL  — persists conversations                      │
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
- Renders the final result (narrative, places) in a results panel
- Left sidebar with collapsible chat history; clicking an item loads the full conversation
- All `/api/*` requests are proxied to the backend — the browser never talks to the backend directly

### Backend — NestJS (port 8000)

Orchestrates the chat lifecycle. Key responsibilities:

| Concern | Detail |
|---------|--------|
| **Persistence** | TypeORM + PostgreSQL. Each conversation is a row with a `jsonb` content column storing the full `ChatInterface`. |
| **Live state** | Redis key `chat:{uuid}` holds the in-progress `ChatInterface` (content, agentStatus, result). Deleted after the conversation stops. |
| **AI dispatch** | `POST /api/chat` to the AI Agent is fire-and-forget — Backend returns immediately while the agent works in the background. |
| **Polling** | `GET /api/chat/:id` reads Redis first; falls back to PostgreSQL for completed conversations whose Redis key has been deleted. |

**Endpoints:**

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/chat/new` | Create conversation in PostgreSQL + Redis, call AI Agent, return `{ id }` |
| `GET` | `/api/chat/history` | Return all conversations ordered by creation date (id, title, createdAt) |
| `GET` | `/api/chat/:id` | Return live `ChatInterface` from Redis, or persisted version from PostgreSQL |
| `POST` | `/api/chat/:id/stop` | Persist final state to PostgreSQL, delete Redis key, mark conversation stopped |
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
│   │   ├── chat.py                    — ChatRequest, ChatResponse schemas
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
| `POST` | `/api/chat` | Run the ReAct agent for a conversation |
| `GET` | `/api/health` | Health check |

### PostgreSQL (port 5432)

Stores every conversation permanently. Schema (auto-created by TypeORM in dev):

```
conversations
  uuid        uuid  PRIMARY KEY
  title       varchar(500)
  content     jsonb          — full ChatInterface object
  created_at  timestamptz
  updated_at  timestamptz
```

### Redis (internal, no host port)

Ephemeral cache for live conversations. Each key `chat:{uuid}` holds the full `ChatInterface` as JSON. Written by both the Backend and the AI Agent; deleted by Backend on `stopChat`.

---

## Chat workflow

```
User types query and submits
        │
        ▼
POST /api/chat/new  →  Backend
  · Creates PostgreSQL row (title = query)
  · Writes ChatInterface to Redis  (agentStatus: isThinking)
  · Fires async POST /api/chat to AI Agent
  · Returns { id }
        │
        ▼
AI Agent receives request
  · LLM decides to call geocode_location
  · Writes "Calling tool geocode_location" to Redis
        │
        ▼
[tools node]  — geocode_location resolves location to GPS coords
  · LLM decides to call search_places
  · Writes "Calling tool search_places" to Redis
        │
        ▼
[tools node]  — search_places fetches attractions, restaurants, hotels
  · LLM writes travel narrative (no more tool calls)
  · Writes final ChatMessage  (agentStatus: hasReplied)
  · Sets ChatInterface.agentStatus = hasReplied in Redis
        │
        ▼
Frontend detects agentStatus === "hasReplied" on next poll
  · Displays result panel
  · Calls POST /api/chat/:id/stop
        │
        ▼
Backend stopChat
  · Persists full ChatInterface to PostgreSQL content column
  · Deletes Redis key
  · Sets status: isStopped
        │
        ▼
Sidebar refreshes history list  (chat-completed event)
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

ChatMessage {
  actor:       ChatActor
  text:        string
  timestamp:   datetime
  agentStatus: AgentStatus | null   // null for user messages
}

ChatInterface {
  id:          uuid
  title:       string
  content:     ChatMessage[]
  status:      ChatStatus
  agentStatus: AgentStatus
  result?: {
    location:  string
    narrative: string
    places:    Place[]
  }
}
```
