# Design and Build a Stateful AI Agent

This article walks through the design and implementation of a stateful AI agent, using a travel guide as the example. The agent takes a free-text location query, calls real external APIs to gather data, and uses Claude to write a travel narrative — while streaming live progress to the browser and supporting multi-turn conversations.

The focus is on the architectural decisions that make this work in practice: how to run a LangGraph ReAct agent across multiple services, keep live state visible to the frontend without WebSockets, and reconstruct conversation history across turns.

This was also my first time using FastAPI and LangGraph.

---

## What Makes an Agent "Stateful"?

A stateless agent has no memory between steps. Each call is independent.

A stateful agent maintains context across steps — the LLM's messages, tool results, and intermediate outputs accumulate in a shared state object. The model reads the full message history on each iteration and decides what to do next.

In practice, statefulness requires answers to three questions:

1. **Where does state live?** (in-memory, Redis, a database)
2. **Who can read and write it?** (one service, multiple services)
3. **How does the client observe it changing?** (polling, WebSockets, SSE)

The architecture below makes deliberate choices for each.

---

## Architecture Overview

```
Browser (Next.js)
    │  polls GET /api/chat/{id} every 2s
    ▼
Backend (NestJS)              ──── PostgreSQL (persistence)
    │  fire-and-forget POST         Redis (live agent state)
    ▼                               ▲
AI Agent (FastAPI + LangGraph) ─────┘
    │  writes progress to Redis on each tool call
    ▼
  agent ⇄ tools  (ReAct loop)
```

**Redis is the shared live-state channel.** The backend fires the AI agent request without waiting for it to finish, and the browser polls the backend every two seconds. The agent writes progress directly to Redis as it calls each tool, so the frontend sees updates in near real-time without WebSockets or server-sent events.

**PostgreSQL is the persistent store.** When a conversation ends, the flat `ChatMessage[]` array is written to Postgres and the Redis key is deleted. History queries go to Postgres; live queries go to Redis.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Next.js 15, React 19, Tailwind CSS 4 |
| Backend | NestJS 11, TypeORM, ioredis |
| AI Agent | FastAPI, LangGraph, LangChain Anthropic |
| LLM | Claude (claude-sonnet-4-6) |
| External APIs | Google Geocoding API, Google Places API |
| Storage | PostgreSQL (persistence), Redis (live state) |
| Infrastructure | Docker Compose |

---

## Step 1 — Design a True ReAct Agent with LangGraph

The first design decision is how to structure the agent's execution. A hardcoded pipeline (`planner → researcher → synthesizer`) works but is brittle — the sequence is fixed in code, not driven by the model. A real agent lets the LLM decide which tools to call, in what order, and when it has enough information to respond.

LangGraph's ReAct pattern implements this as a cycle: the agent node calls the LLM, the LLM emits tool calls, a tools node executes them and appends results to the message history, then the agent node runs again. The loop continues until the LLM produces a final response with no tool calls.

### Define Agent State

`MessagesState` is LangGraph's built-in state type that accumulates the full conversation as a list of `BaseMessage` objects. Tool calls, tool results, and LLM responses all append to the same list:

```python
from langgraph.graph import MessagesState

class AgentState(MessagesState):
    raw_query: str
```

### Define Tools as Classes

Tools wrap external API calls. Each tool is a class with its HTTP logic in methods, and a module-level `@tool` function that LangChain can bind to the LLM:

```python
class GeocodingTool:
    _URL = "https://maps.googleapis.com/maps/api/geocode/json"

    async def geocode(self, query: str) -> tuple[str, float, float]:
        async with httpx.AsyncClient() as client:
            resp = await client.get(self._URL, params={"address": query, "key": settings.google_api_key})
            data = resp.json()
        result = data["results"][0]
        return result["formatted_address"], result["geometry"]["location"]["lat"], result["geometry"]["location"]["lng"]

    async def resolve(self, query: str) -> dict:
        try:
            name, lat, lng = await self.geocode(query)
            return {"location_name": name, "latitude": lat, "longitude": lng}
        except ValueError as e:
            return {"error": str(e)}

_geocoding_tool = GeocodingTool()

@tool
async def geocode_location(query: str) -> dict:
    """Resolve a free-text travel query to a canonical place name and GPS coordinates. Always call this first."""
    return await _geocoding_tool.resolve(query)
```

The `@tool` function must stay at module level so LangChain can inspect its signature and docstring to describe it to the LLM. The class handles the actual logic.

### Implement the Agent Node as a Class

`TravelAgent` encapsulates the LLM, the system prompt, and the tools it has access to. The `invoke` method is the graph node function:

```python
class TravelAgent:
    _SYSTEM = """You are an enthusiastic and knowledgeable travel guide.

When given a travel query:
1. Call geocode_location to resolve the destination to a canonical name and GPS coordinates.
2. Call search_places with the returned latitude and longitude to find nearby venues.
3. Write a comprehensive 2-3 paragraph travel narrative about the destination based on the venues found.

Write the narrative as natural prose. Do not call any more tools after writing it."""

    def __init__(self):
        self._llm = ChatAnthropic(
            model="claude-sonnet-4-6",
            api_key=settings.anthropic_api_key,
            max_tokens=8192,
        ).bind_tools([geocode_location, search_places])

    async def invoke(self, state: AgentState) -> dict:
        messages = state["messages"]
        if not any(isinstance(m, SystemMessage) for m in messages):
            messages = [SystemMessage(content=self._SYSTEM)] + list(messages)
        response = await self._llm.ainvoke(messages)
        return {"messages": [response]}
```

### Build the ReAct Graph

`AgentGraph` assembles the loop. The conditional edge after the agent node checks whether the LLM returned tool calls — if yes, run the tools and loop back; if no, the narrative is ready and the graph ends:

```python
class AgentGraph:
    def build(self):
        travel_agent = TravelAgent()
        tool_node = ToolNode([geocode_location, search_places])

        graph = StateGraph(AgentState)
        graph.add_node("agent", travel_agent.invoke)
        graph.add_node("tools", tool_node)
        graph.add_edge(START, "agent")
        graph.add_conditional_edges("agent", self._should_continue, {"tools": "tools", "end": END})
        graph.add_edge("tools", "agent")
        return graph.compile()

    @staticmethod
    def _should_continue(state: AgentState) -> str:
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and last.tool_calls:
            return "tools"
        return "end"
```

The key difference from a hardcoded pipeline: the LLM decides at runtime which tools to call. If the user asks something that doesn't need geocoding, the model can skip it. If a tool fails, the model sees the error in the message history and can try a different approach.

---

## Step 2 — Centralise Dependency Injection

With multiple services (graph, Redis, chat service), wiring dependencies by hand across files creates coupling and makes testing hard. A single `di.py` owns all construction:

```python
from functools import lru_cache

@lru_cache(maxsize=1)
def get_graph():
    return AgentGraph().build()

@lru_cache(maxsize=1)
def get_redis():
    return RedisClient().get()

@lru_cache(maxsize=1)
def get_chat_service() -> ChatService:
    return ChatService(
        graph=get_graph(),
        redis=get_redis(),
        logger=get_logger("chat_service"),
    )
```

`@lru_cache(maxsize=1)` acts as the singleton — the first call constructs the object, every subsequent call returns the cached instance. No global variables, no manual `if _instance is None` guards.

`ChatService` receives its dependencies through the constructor — it never calls `get_graph()` or `get_redis()` directly:

```python
class ChatService:
    def __init__(self, graph, redis, logger: logging.Logger):
        self._graph = graph
        self._redis = redis
        self._logger = logger
```

The FastAPI router resolves everything through `Depends`:

```python
@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    service: ChatService = Depends(get_chat_service),
):
    return await service.handle(request)
```

---

## Step 3 — Decouple the Agent from the API Layer

A common mistake is running the agent synchronously inside the API request. For a pipeline that takes 30–60 seconds, this means the client holds an open HTTP connection for the entire duration — fragile, non-resumable, and hard to scale.

The solution is **fire-and-forget**: the backend returns immediately with a conversation ID, and the agent runs concurrently in the background.

```typescript
// NestJS ChatService
async newChat(message: string): Promise<{ id: string }> {
  const id = uuidv4();
  const chatObject: ChatInterface = {
    id,
    title: message,
    content: [{ actor: ChatActor.user, text: message, timestamp: new Date(), type: 'text' }],
    status: ChatStatus.isActive,
    agentStatus: AgentStatus.isThinking,
  };

  await this.conversationRepo.save({ uuid: id, title: message, content: chatObject.content });
  await this.redisService.setJson(`chat:${id}`, chatObject);
  this.agentService.call(id, message, []);  // no await — fire and forget
  return { id };
}
```

The client gets `{ id }` back in milliseconds. It then starts polling and sees the agent's progress as it unfolds. If the client disconnects and reconnects, it picks up from wherever the agent left off — because state is in Redis, not in memory.

---

## Step 4 — Type the Message Contract

`ChatMessage.text` is either a plain string (tool call announcements, errors) or a `ChatContent` object (the final structured reply). The shape of `text` is the rendering contract — no separate `type` flag needed.

```typescript
interface ChatContent {
  location: string;
  narrative: string;
  places: ChatPlace[];
}

interface ChatMessage {
  actor: "User" | "Agent";
  text: string | ChatContent;
  timestamp: Date;
  agentStatus?: "isThinking" | "hasReplied" | null;
}
```

The AI agent builds `ChatContent` directly — no `json.dumps` or string encoding:

```python
chat_obj.content.append(
    self._make_message(
        ChatContent(location=location_name, narrative=narrative, places=places),
        AgentStatus.has_replied,
    )
)
```

Pydantic serializes `ChatContent` as a nested JSON object in `model_dump_json()`. The message array stores a real object, not an embedded string.

The frontend distinguishes the two cases with `typeof`:

```typescript
const finalMsg = [...chat.content].reverse().find((m) => m.agentStatus === "hasReplied");

if (finalMsg && typeof finalMsg.text === "object") {
  setResult(finalMsg.text);                      // → ResultsPanel
} else {
  setError(finalMsg?.text as string ?? "No response.");  // → error box
}
```

No `JSON.parse` anywhere. The message array is the single source of truth — structured results are real objects stored as native JSON, not strings embedded inside JSON.

---

## Step 5 — Stream State to the UI

### Reading Tool Calls in Real Time

LangGraph's `stream_mode="updates"` emits a dict per node completion. When the agent node returns an `AIMessage` with `tool_calls`, those calls are announced to Redis immediately — before the tools node even starts executing:

```python
async for update in self._graph.astream(
    {"messages": initial_messages, "raw_query": request.message},
    stream_mode="updates",
):
    for node_name, node_output in update.items():
        new_msgs = node_output.get("messages", [])

        if node_name == "agent" and new_msgs:
            last = new_msgs[-1]
            if isinstance(last, AIMessage) and last.tool_calls:
                for tc in last.tool_calls:
                    chat_obj.content.append(
                        self._make_message(f"Calling tool {tc['name']}", AgentStatus.is_thinking, "text")
                    )

        await self._redis.set(key, chat_obj.model_dump_json())
```

The tool names come directly from `AIMessage.tool_calls` — the LLM's actual decision. There is no hardcoded list of steps to announce. If the model decides to call a different tool or skip one, the UI reflects that automatically.

### Polling on the Frontend

The frontend uses a recursive `setTimeout` rather than `setInterval`. This prevents poll requests from stacking up if a response is slow:

```typescript
async function schedulePoll(id: string) {
  const chat = await pollChat(id);
  agentStatusRef.current = chat.agentStatus ?? null;

  // Only show agent messages belonging to the current turn
  const allAgentMessages = chat.content.filter((m) => m.actor === "Agent");
  const currentTurnMessages = allAgentMessages.slice(agentMessageOffsetRef.current);
  setMessages(currentTurnMessages);

  if (chat.agentStatus === "hasReplied") {
    endConversation();
    const finalMsg = [...chat.content].reverse().find((m) => m.agentStatus === "hasReplied");
    if (finalMsg?.type === "json") {
      setResult(JSON.parse(finalMsg.text) as ChatResult);
    } else {
      setError(finalMsg?.text ?? "No response.");
    }
    await stopChat(id);
    window.dispatchEvent(new CustomEvent("chat-completed")); // sidebar refreshes
  } else if (chat.agentStatus === "isThinking") {
    pollTimeoutRef.current = setTimeout(() => schedulePoll(id), 2000);
  }
}
```

`agentMessageOffsetRef` tracks how many agent messages existed before the current turn started. Slicing from that offset means the tool-call log shows only messages from the ongoing turn, not from previous turns that already have their own rendered panels.

A "Thinking…" indicator appears when consecutive polls return the same number of tool messages — meaning the agent is processing but hasn't announced the next tool yet:

```typescript
const thinkingCount = currentTurnMessages.filter((m) => m.agentStatus === "isThinking").length;
setIsThinkingIdle(thinkingCount === prevThinkingCountRef.current);
prevThinkingCountRef.current = thinkingCount;
```

---

## Step 6 — Multi-Turn Conversations

A single-turn agent is useful; a conversational agent is far more powerful. The user should be able to say "what's in Melbourne?" and follow up with "for a weekend trip" without repeating the city.

### Passing History to the Agent

The backend `continueChat` endpoint reads the full message history from Redis (active conversation) or PostgreSQL (after stop), appends the new user message, and forwards the complete history to the AI agent:

```typescript
async continueChat(id: string, message: string): Promise<{ accepted: true }> {
  const cached = await this.redisService.getJson<ChatInterface>(`chat:${id}`);
  const existingMessages = cached
    ? cached.content
    : (await this.conversationRepo.findOne({ where: { uuid: id } })).content as ChatMessage[];

  const chatObject: ChatInterface = {
    id,
    title: cached?.title ?? null,
    content: [...existingMessages, { actor: ChatActor.user, text: message, timestamp: new Date(), type: 'text' }],
    status: ChatStatus.isActive,
    agentStatus: AgentStatus.isThinking,
  };

  await this.redisService.setJson(`chat:${id}`, chatObject);
  this.agentService.call(id, message, existingMessages);  // full history passed
  return { accepted: true };
}
```

The AI agent reconstructs LangChain messages from the history before invoking the graph. User turns become `HumanMessage`; completed agent replies (`hasReplied`, `type: "json"`) become `AIMessage`. Tool-call progress messages (`isThinking`) are skipped — they are UI artefacts, not meaningful conversation context:

```python
@staticmethod
def _build_messages(history: list, new_message: str) -> list:
    messages = []
    for msg in history:
        if msg.actor == "User":
            messages.append(HumanMessage(content=msg.text))
        elif msg.actor == "Agent" and msg.agentStatus == "hasReplied":
            messages.append(AIMessage(content=msg.text))
    messages.append(HumanMessage(content=new_message))
    return messages
```

### Preserving Completed Turns in the UI

When the user submits a follow-up, the frontend moves the current turn's messages and result into a `completedTurns` array before resetting for the next turn:

```typescript
async function handleContinue(message: string) {
  if (userMessage) {
    setCompletedTurns((prev) => [
      ...prev,
      {
        userMessage,
        thinkingMessages: messages.filter((m) => m.agentStatus === "isThinking"),
        result,
      },
    ]);
  }
  agentMessageOffsetRef.current += messages.length;  // advance the slice window
  // reset current turn, call continueChat, start polling
}
```

Each completed turn renders its own chat bubble, tool-call log, and results panel. The conversation scrolls naturally — old turns remain visible above while the new one processes below.

### Reconstructing History on Load

When a user opens a saved conversation, the flat `ChatMessage[]` array must be split back into turns. Each `User` message starts a new turn; the subsequent `Agent` messages belong to it until `agentStatus === "hasReplied"` closes the turn:

```typescript
function splitTurns(content: ChatMessage[]): Turn[] {
  const turns: Turn[] = [];
  let userMessage = "";
  let agentMessages: ChatMessage[] = [];

  for (const msg of content) {
    if (msg.actor === "User") {
      userMessage = msg.text;
      agentMessages = [];
    } else if (msg.actor === "Agent") {
      agentMessages.push(msg);
      if (msg.agentStatus === "hasReplied") {
        let result: ChatResult | null = null;
        if (msg.type === "json") {
          try { result = JSON.parse(msg.text) as ChatResult; } catch {}
        }
        turns.push({ userMessage, agentMessages: [...agentMessages], result, error: null });
      }
    }
  }

  return turns;
}
```

All turns except the last go into `completedTurns`. The last turn populates the current-turn state. `agentMessageOffsetRef` is set to the total number of agent messages in all completed turns — so if the user continues from a loaded history, the offset is already correct.

---

## Step 7 — Persist State

When the agent finishes, the backend persists the `ChatMessage[]` array directly to PostgreSQL — not a nested wrapper object:

```typescript
async stopChat(id: string): Promise<{ stopped: true }> {
  const current = await this.redisService.getJson<ChatInterface>(`chat:${id}`);
  await this.conversationRepo.save({
    uuid: id,
    content: current.content,  // flat ChatMessage[] stored in jsonb column
  });
  await this.redisService.del(`chat:${id}`);
  return { stopped: true };
}
```

Storing the message array directly — rather than a `ChatInterface` object that embeds the array — means the DB row is a clean, flat record. Every piece of structured information, including the full result payload for each agent turn, lives inside a `ChatMessage`. Nothing is split across columns.

Here is what an actual `content` column value looks like after a multi-turn conversation about Sydney:

```json
[
  { "actor": "User", "text": "tell me about Sydney",
    "timestamp": "2026-06-18T00:54:52.046000Z", "agentStatus": null },
  { "actor": "Agent", "text": "Calling tool resolve_geocode",
    "timestamp": "2026-06-18T00:54:54.034561Z", "agentStatus": "isThinking" },
  { "actor": "Agent", "text": "Calling tool search_places",
    "timestamp": "2026-06-18T00:54:56.798732Z", "agentStatus": "isThinking" },
  {
    "actor": "Agent",
    "text": {
      "location": "Sydney NSW, Australia",
      "narrative": "Sydney is one of the world's most breathtaking cities...",
      "places": [
        { "name": "Sydney Opera House", "category": "attraction",
          "address": "Bennelong Point, Sydney", "rating": 4.8,
          "description": "", "image_url": null, "source_url": null },
        { "name": "Four Seasons Hotel Sydney", "category": "hotel",
          "address": "199 George Street, The Rocks", "rating": 4.5,
          "description": "", "image_url": null, "source_url": null }
      ]
    },
    "timestamp": "2026-06-18T00:55:10.823519Z",
    "agentStatus": "hasReplied"
  },
  { "actor": "User", "text": "for a weekend trip",
    "timestamp": "2026-06-18T00:55:20.396000Z", "agentStatus": null },
  { "actor": "Agent", "text": "Calling tool resolve_geocode",
    "timestamp": "2026-06-18T00:55:23.012786Z", "agentStatus": "isThinking" },
  { "actor": "Agent", "text": "Calling tool search_places",
    "timestamp": "2026-06-18T00:55:25.368817Z", "agentStatus": "isThinking" },
  {
    "actor": "Agent",
    "text": {
      "location": "Sydney NSW, Australia",
      "narrative": "What a fantastic city for a weekend escape!...",
      "places": [ "..." ]
    },
    "timestamp": "2026-06-18T00:55:39.295973Z",
    "agentStatus": "hasReplied"
  }
]
```

`text` is a native JSON object for structured replies and a plain string for everything else. The frontend reads `typeof text === "object"` to decide whether to render `ResultsPanel` or a plain text message.

The poll endpoint also writes to the DB opportunistically: when it detects `agentStatus === hasReplied` in Redis, it fires a background update so a page refresh never loses a completed reply, even if the user never explicitly triggers `stopChat`:

```typescript
async getChat(id: string): Promise<ChatInterface> {
  const cached = await this.redisService.getJson<ChatInterface>(`chat:${id}`);
  if (cached) {
    if (cached.agentStatus === AgentStatus.hasReplied) {
      this.conversationRepo.update({ uuid: id }, { content: cached.content }).catch(() => {});
    }
    return cached;
  }

  const row = await this.conversationRepo.findOne({ where: { uuid: id } });
  if (!row) throw new NotFoundException(`Conversation ${id} not found`);

  return {
    id: row.uuid,
    title: row.title,
    content: row.content as unknown as ChatMessage[],
    status: ChatStatus.isStopped,
    agentStatus: AgentStatus.hasReplied,
  };
}
```

---

## Key Design Decisions

**ReAct over hardcoded pipeline.** A fixed `planner → researcher → synthesizer` sequence is a workflow, not an agent. The LLM driving tool selection at runtime is what makes the system an actual agent — it can adapt to what the tools return, handle errors gracefully, and generalise to inputs the pipeline wasn't designed for.

**`text: string | ChatContent` as the rendering contract.** The shape of `text` encodes the rendering intent — no separate discriminator field needed. If `typeof text === "object"`, it's a `ChatContent` to render as cards and narrative; if it's a string, it's a plain text message or error. This keeps the data stored in PostgreSQL as proper typed JSON rather than a JSON string embedded inside a JSON object.

**Result embedded in the message, not alongside it.** Putting the structured result (`location`, `narrative`, `places`) inside the `hasReplied` message means the message array is the single source of truth. A multi-turn conversation with ten replies has ten self-contained result payloads — each visible in the flat DB row and reconstructable without joins or extra columns.

**`splitTurns` for history reconstruction.** A flat `ChatMessage[]` is the canonical representation — both in Redis and PostgreSQL. Splitting into turns is a pure function over that array, applied only when needed (history load). This means the storage format never changes based on how many turns a conversation has.

**Redis over WebSockets.** Redis with polling is simpler to operate, trivial to debug (inspect the key directly with `redis-cli`), and scales horizontally without sticky sessions. For a 2-second poll interval, the overhead is negligible.

**Fire-and-forget over synchronous execution.** Long-running agents should never block an HTTP connection. Returning a job ID immediately and letting the client poll is more resilient — the client can reconnect, retry, or time out without corrupting the agent's execution.

**Constructor injection over module-level singletons.** `ChatService(graph, redis, logger)` is explicit about what it needs. Dependencies are testable — swap in a mock graph or a mock Redis in tests without patching globals.

**`@lru_cache` as the singleton mechanism.** One decorator replaces the `global _instance / if _instance is None` pattern. The function signature documents what gets constructed; the cache ensures it happens once.

**Flat `ChatMessage[]` in PostgreSQL.** Storing the message array directly in the `jsonb` column (rather than a nested `ChatInterface` wrapper) keeps the schema honest. Querying, debugging with `psql`, and reconstructing state all operate on the same shape.

---

## Source Code

The full implementation — LangGraph ReAct agent, NestJS backend, Next.js frontend, and Docker Compose setup — is available on GitHub:

**https://github.com/ngodinhloc/tourguide-agent**

To run it locally:

```bash
git clone https://github.com/ngodinhloc/tourguide-agent.git
cd tourguide-agent
cp ai-agent/.env.example ai-agent/.env
# Add ANTHROPIC_API_KEY and GOOGLE_API_KEY to ai-agent/.env
docker-compose up --build
```

Open [http://localhost:3000](http://localhost:3000) and ask it about any city.
