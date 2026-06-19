# Tour Guide Agent

An AI travel guide. Type a free-text location query — "anything to see in Sydney" or "weekend in Melbourne" — and get back a curated guide with attractions, restaurants, and hotels. Claude writes the narrative; Google Places provides the data. Multi-turn conversations work, so a follow-up like "what about for families?" carries on from where the last reply left off.

---

## Screenshots

**Streaming tool-call log while the agent processes**

![Agent streaming tool calls and loading skeleton](./screenshot_1.png)

**Completed travel guide with narrative and place cards**

![Completed travel guide](./screenshot_2.png)

![Continue conversation follow-up](./screenshot_3.png)

![Multi-turn conversation in progress](./screenshot_4.png)

![Sidebar with saved conversation history](./screenshot_5.png)

---

## Architecture

![Architecture overview](./architecture.png)

```
┌──────────────────────────────────────────────────────────────────┐
│  Browser                                                         │
│  Next.js frontend  (port 3000)                                   │
│  · Search bar, streaming tool-call log, results panel            │
│  · Multi-turn chat with completed-turn history                   │
│  · Sidebar with conversation history                             │
└────────────────────────┬─────────────────────────────────────────┘
                         │ HTTP  /api/*  (Next.js proxy)
┌────────────────────────▼─────────────────────────────────────────┐
│  Backend  (NestJS · port 8000)                                   │
│  · REST chat API                                                 │
│  · PostgreSQL  — persists conversations as ChatMessage[]         │
│  · Redis       — live chat state during agent processing         │
│  · Fires async POST to AI Agent (fire-and-forget)                │
└──────────┬───────────────────────────┬───────────────────────────┘
           │ async POST /api/chat       │ read / write
           │                           │
┌──────────▼───────────────┐   ┌───────▼────────────┐
│  AI Agent                │   │  Redis             │
│  FastAPI · port 8001     │──▶│  key: chat:{uuid}  │
│  LangGraph ReAct loop    │   └────────────────────┘
│  agent ⇄ tools           │
│  MCP_PROTOCOL=MCP|REST   │
└──────────┬───────────────┘
           │ MCP (streamable HTTP) or REST
┌──────────▼───────────────┐
│  MCP Server              │
│  FastMCP · port 8002     │
│  POST /mcp/  — MCP       │
│  GET  /api/tools  — REST │
│  POST /api/tool/call      │
│  resolve_geocode          │
│  search_places            │
└──────────────────────────┘
```

---

## Services

| Service | Port | Directory | Stack |
|---------|------|-----------|-------|
| postgres | 5432 | — | PostgreSQL 17 |
| redis | internal | — | Redis 7 |
| mcp-server | 8002 | `mcp-server/` | FastMCP + FastAPI |
| ai-agent | 8001 | `ai-agent/` | FastAPI + LangGraph + LangChain Anthropic |
| backend | 8000 | `backend/` | NestJS 11 + TypeORM |
| frontend | 3000 | `frontend/` | Next.js 15 + React 19 + Tailwind CSS 4 |

### Frontend (port 3000)

- Search bar for free-text location queries
- Polls `GET /api/chat/{id}` every 2 seconds while the agent is processing
- Live tool-call log (`Calling tool resolve_geocode`, etc.) that updates as the agent works
- `Thinking…` indicator between tool calls when the agent is processing but hasn't announced the next step
- Final reply renders as a narrative paragraph + place cards (`ResultsPanel`)
- Multi-turn UI — completed turns stay on screen; each new turn processes below
- Left sidebar lists saved conversations; clicking one reloads all turns

### Backend (port 8000)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/chat/new` | Create conversation in PostgreSQL + Redis, call AI Agent, return `{ id }` |
| `POST` | `/api/chat/:id/cont` | Append user message to history, call AI Agent, return `{ accepted: true }` |
| `GET` | `/api/chat/history` | Return all conversations (id, title, createdAt) |
| `GET` | `/api/chat/:id` | Live `ChatInterface` from Redis, or persisted version from PostgreSQL |
| `POST` | `/api/chat/:id/stop` | Persist `ChatMessage[]` to PostgreSQL, delete Redis key |
| `GET` | `/api/health` | Health check |

### AI Agent (port 8001)

Runs a LangGraph ReAct agent triggered by `POST /api/chat`. The LLM decides which tools to call, in what order, and when it has enough to reply. Tools are delegated to the MCP server via `McpTools` (MCP protocol) or `RestTools` (REST), selected by `MCP_PROTOCOL`.

**ReAct loop:**

```
agent node  →  calls LLM with tools bound
     │
     ├── LLM returns tool_calls  →  tools node executes  →  calls MCP server  →  back to agent
     │
     └── LLM returns narrative (no tool_calls)  →  END
```

**Tool client abstraction:**

```
ToolClientFactory(mcp_server_url, mcp_protocol)
    .create()
        ├── MCP_PROTOCOL=MCP  →  McpTools   (FastMCP Client over streamable HTTP)
        └── MCP_PROTOCOL=REST →  RestTools  (httpx POST /api/tool/call)
```

`ToolClientInterface` (ABC) enforces that both `McpTools` and `RestTools` implement `call(name, arguments)`. Python raises `TypeError` at instantiation if the method is missing.

**Multi-turn context:** The request carries the full conversation `history`. `ChatManager.build_messages` reconstructs it as LangChain messages — user turns become `HumanMessage`, completed agent replies become `AIMessage`, and tool-call progress messages are skipped — so the LLM reads the full dialogue before responding.

**Module structure:**

```
app/
├── agent/
│   ├── contracts/agent_interface.py         — AgentState (extends MessagesState)
│   ├── tools/
│   │   ├── tool_client_interface.py         — ToolClientInterface (ABC)
│   │   ├── mcp_tools.py                     — McpTools (FastMCP Client)
│   │   ├── rest_tools.py                    — RestTools (httpx)
│   │   ├── tool_client_factory.py           — ToolClientFactory
│   │   └── tools.py                         — @tool resolve_geocode, @tool search_places
│   ├── agent.py                             — Agent class (LLM + system prompt)
│   └── agent_graph.py                       — AgentGraph class (ReAct graph)
├── configs/settings.py                      — Settings (Pydantic BaseSettings)
├── container.py                             — Container class (cached_property singletons)
├── main.py                                  — FastAPI app, middleware, routers
├── routers/
│   ├── contracts/chat_interface.py          — ChatInterface, ChatMessage, AgentStatus types
│   ├── chat_router.py                       — POST /api/chat
│   └── health_router.py                     — GET /api/health
└── services/
    ├── chat_service.py                      — ChatService (graph execution, Redis streaming)
    ├── chat_manager.py                      — ChatManager (message building, Redis reads/writes)
    └── redis_client.py                      — RedisClient
```

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/chat` | Run the ReAct agent (new or continued conversation) |
| `GET` | `/api/health` | Health check |

### MCP Server (port 8002)

Exposes the two Google API tools over both MCP protocol and REST. The AI agent can call either protocol via `MCP_PROTOCOL`. All incoming requests are logged — MCP calls include the full JSON-RPC envelope.

**Tools:**

| Tool | What it does | API |
|------|-------------|-----|
| `resolve_geocode` | Resolves free-text query to canonical place name + GPS coordinates | Google Geocoding API |
| `search_places` | Fetches nearby attractions, restaurants, and hotels | Google Places API |

**Module structure:**

```
app/
├── configs/settings.py                      — Settings (Pydantic BaseSettings)
├── container.py                             — Container class (GeocodingTool, PlacesTool)
├── fast_mcp.py                              — FastMCP instance + @fast_mcp.tool() definitions
├── main.py                                  — FastAPI app, lifespan wired to FastMCP, /mcp mount
├── routers/
│   ├── contracts/tool_interface.py          — TOOLS_SCHEMA, TOOL_DISPATCH, ToolCallRequest
│   ├── tools_router.py                      — GET /api/tools, POST /api/tool/call
│   └── health_router.py                     — GET /api/health
└── tools/
    ├── geocoding_tool.py                    — GeocodingTool class
    └── places_tool.py                       — PlacesTool class
```

| Method | Path | Protocol | Description |
|--------|------|----------|-------------|
| `POST` | `/mcp/` | MCP | FastMCP streamable HTTP endpoint |
| `GET` | `/api/tools` | REST | List tool schemas |
| `POST` | `/api/tool/call` | REST | Call a tool by name |
| `GET` | `/api/health` | REST | Health check |

---

## Data model

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
  text:        string | ChatContent   // string for tool calls/errors; ChatContent for the final reply
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

The PostgreSQL `content` column stores a flat `ChatMessage[]` directly as `jsonb`. Tool-call progress messages (`isThinking`) and the final reply (`hasReplied`) live in the same array. The frontend uses `typeof text === "object"` to decide whether to render a results panel or a plain text line.

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
          "rating": 4.8
        }
      ]
    },
    "timestamp": "2026-06-18T00:55:10.823519Z",
    "agentStatus": "hasReplied"
  }
]
```

---

## Quick start

```bash
# 1. Fill in API keys
cp ai-agent/.env.example ai-agent/.env
cp mcp-server/.env.example mcp-server/.env
# edit ai-agent/.env   — set ANTHROPIC_API_KEY
# edit mcp-server/.env — set GOOGLE_API_KEY

# 2. Start all services
docker-compose up --build
```

Open [http://localhost:3000](http://localhost:3000).

### Required API keys

| Key | Service | Where to get |
|-----|---------|-------------|
| `ANTHROPIC_API_KEY` | `ai-agent/.env` | [console.anthropic.com](https://console.anthropic.com) |
| `GOOGLE_API_KEY` | `mcp-server/.env` | Google Cloud Console — enable **Geocoding API** and **Places API** |
