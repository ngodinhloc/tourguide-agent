# Build a Stateful AI Agent with LangGraph, NestJS, and Next.js

I built a travel guide app where Claude acts as the agent. You type a free-text query like "anything to see in Sydney", and the agent calls Google Geocoding to resolve the location, then Google Places to find venues, then writes a narrative. Multi-turn conversations are supported — a follow-up like "for a weekend trip?" keeps the context without restarting.

This was my first time using FastAPI and LangGraph. This article covers the main design decisions: how to build a real ReAct agent (not a hardcoded pipeline), how to stream progress to the browser without WebSockets, and how to handle multi-turn conversations across services.

![Agent streaming tool calls and loading skeleton](./screenshot_1.png)

*The streaming tool-call log. Each tool the agent calls appears as a new line while the frontend polls every 2 seconds.*

---

## Architecture

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

Redis is the shared channel between the backend and the agent. The backend fires the agent request without waiting, and the browser polls every 2 seconds. The agent writes to Redis after each node — so the frontend sees updates without WebSockets or SSE.

PostgreSQL is for persistence. When a conversation ends, the full `ChatMessage[]` array goes into Postgres and the Redis key is deleted. Live reads hit Redis; history reads hit Postgres.

---

## Tech stack

| Layer | Technology |
|-------|-----------|
| Frontend | Next.js 15, React 19, Tailwind CSS 4 |
| Backend | NestJS 11, TypeORM, ioredis |
| AI Agent | FastAPI, LangGraph, LangChain Anthropic |
| LLM | Claude (`claude-sonnet-4-6`) |
| External APIs | Google Geocoding API, Google Places API |
| Storage | PostgreSQL (persistence), Redis (live state) |
| Infrastructure | Docker Compose |

---

## Step 1 — Build a Real ReAct Agent

A hardcoded pipeline (`geocode → search → write`) works but it is a workflow, not an agent. The LLM has no decision power. LangGraph's ReAct pattern gives the model control: the agent node calls the LLM, the LLM emits tool calls, a tools node executes them and appends results to the message history, then the agent node runs again. The loop continues until the LLM replies with no tool calls.

### Define agent state

`MessagesState` is LangGraph's built-in state type. It accumulates the full conversation as a list of `BaseMessage` objects — tool calls, tool results, and LLM responses all append to the same list:

```python
from langgraph.graph import MessagesState

class AgentState(MessagesState):
    raw_query: str
```

### Separate tool logic from the @tool function

Each tool is a class that handles the HTTP call. A module-level `@tool` function wraps it — LangChain needs the function at module level to inspect its signature and docstring:

```python
class GeocodingTool:
    _URL = "https://maps.googleapis.com/maps/api/geocode/json"

    async def geocode(self, query: str) -> tuple[str, float, float]:
        async with httpx.AsyncClient() as client:
            resp = await client.get(self._URL, params={"address": query, "key": settings.google_api_key})
            resp.raise_for_status()
            data = resp.json()
        result = data["results"][0]
        return result["formatted_address"], result["geometry"]["location"]["lat"], result["geometry"]["location"]["lng"]

    async def resolve(self, query: str) -> dict:
        try:
            name, lat, lng = await self.geocode(query)
            return {"location_name": name, "latitude": lat, "longitude": lng}
        except ValueError as e:
            return {"error": str(e)}

@tool
async def resolve_geocode(query: str) -> dict:
    """Resolve a free-text travel query to a canonical place name and GPS coordinates. Always call this first."""
    return await GeocodingTool().resolve(query)
```

The `@tool` function stays thin. The class handles the real logic and is easy to test in isolation.

### Agent node as a class

`Agent` holds the LLM, the system prompt, and the tools. The `invoke` method is the graph node:

```python
class Agent:
    _SYSTEM = """You are an enthusiastic and knowledgeable travel guide.

When given a travel query:
1. Call resolve_geocode to resolve the destination to a canonical name and GPS coordinates.
2. Call search_places with the returned latitude and longitude to find nearby venues.
3. Write a comprehensive 2-3 paragraph travel narrative about the destination based on the venues found.

Write the narrative as natural prose. Do not call any more tools after writing it."""

    def __init__(self):
        self._llm = ChatAnthropic(
            model="claude-sonnet-4-6",
            api_key=settings.anthropic_api_key,
            max_tokens=8192,
        ).bind_tools(tools)

    async def invoke(self, state: AgentState) -> dict:
        messages = state["messages"]
        if not any(isinstance(m, SystemMessage) for m in messages):
            messages = [SystemMessage(content=self._SYSTEM)] + list(messages)
        response = await self._llm.ainvoke(messages)
        return {"messages": [response]}
```

### Assemble the ReAct graph

```python
class AgentGraph:
    def build(self):
        agent = Agent()
        tool_node = ToolNode(tools)

        graph = StateGraph(AgentState)
        graph.add_node("agent", agent.invoke)
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

The conditional edge is the key part. If the last message has tool calls, go to tools and loop back. If not, the narrative is done and the graph ends. The LLM decides which tools to call at runtime — if a query doesn't need geocoding, the model can skip it.

---

## Step 2 — Centralise Dependency Injection

With the graph, Redis client, `ChatManager`, and `ChatService` all depending on each other, you need a single place to wire them together. A `Container` class with `@cached_property` does this cleanly:

```python
class Container:
    def logger(self, name: str) -> logging.Logger:
        return logging.getLogger(name)

    @cached_property
    def agent_graph(self):
        return AgentGraph().build()

    @cached_property
    def redis_client(self):
        return RedisClient().get()

    @cached_property
    def chat_manager(self) -> ChatManager:
        return ChatManager(self.redis_client)

    @cached_property
    def chat_service(self) -> ChatService:
        return ChatService(
            agent_graph=self.agent_graph,
            chat_manager=self.chat_manager,
            logger=self.logger("chat_service"),
        )

container = Container()
```

`@cached_property` acts as the singleton — the first access constructs the object, every subsequent access returns the cached instance. No global variables, no `if _instance is None` guards.

`ChatService` receives everything through its constructor. It never imports `container` directly:

```python
class ChatService:
    def __init__(self, agent_graph, chat_manager: ChatManager, logger: logging.Logger):
        self._graph = agent_graph
        self._message_manager = chat_manager
        self._logger = logger
```

The FastAPI router resolves from the container via `Depends`:

```python
@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    service: ChatService = Depends(lambda: container.chat_service),
):
    return await service.handle(request)
```

---

## Step 3 — Decouple the Agent from the API Layer

The obvious approach is to run the agent synchronously inside the request handler and wait for it to finish. For a pipeline that can take 30–60 seconds, this holds an HTTP connection open for the entire duration. It is fragile, non-resumable, and hard to scale.

The fix is fire-and-forget. The backend returns a conversation ID immediately, and the agent runs in the background:

```typescript
// NestJS ChatService
async newChat(message: string): Promise<{ id: string }> {
  const id = uuidv4();
  const chatObject: ChatInterface = {
    id,
    title: message,
    content: [{ actor: ChatActor.user, text: message, timestamp: new Date() }],
    status: ChatStatus.isActive,
    agentStatus: AgentStatus.isThinking,
  };

  await this.conversationRepo.save({ uuid: id, title: message, content: chatObject.content });
  await this.redisService.setJson(`chat:${id}`, chatObject);
  this.agentService.call(id, message, []);  // no await
  return { id };
}
```

The client gets `{ id }` back in milliseconds. It starts polling and sees the agent's progress as it writes to Redis. If the client disconnects and reconnects, it picks up from wherever the agent stopped — because state is in Redis, not in memory.

---

## Step 4 — Type the Message Contract

`ChatMessage.text` is either a plain string (tool call announcements, errors) or a `ChatContent` object (the final structured reply). The type of `text` is the rendering contract — no separate discriminator field needed:

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

The AI agent builds `ChatContent` directly — no `json.dumps`, no string encoding:

```python
chat_obj.content.append(
    self._make_message(
        ChatContent(location=location_name, narrative=narrative, places=places),
        AgentStatus.has_replied,
    )
)
```

Pydantic serializes `ChatContent` as a nested JSON object. The message array stores a real object, not an embedded string.

The frontend uses `typeof` to decide how to render:

```typescript
const finalMsg = [...chat.content].reverse().find((m) => m.agentStatus === "hasReplied");

if (finalMsg && typeof finalMsg.text === "object") {
  setResult(finalMsg.text);          // → ResultsPanel
} else {
  setError(finalMsg?.text as string ?? "No response.");
}
```

No `JSON.parse` anywhere. The message array is the single source of truth.

---

## Step 5 — Stream State to the UI

### Announce tool calls in real time

LangGraph's `stream_mode="updates"` emits a dict per node completion. When the agent node returns an `AIMessage` with `tool_calls`, those calls are written to Redis immediately — before the tools node even starts executing:

```python
async def _stream_graph(self, key, chat_obj, initial_messages, raw_query):
    all_messages = list(initial_messages)
    error = None
    try:
        async for update in self._graph.astream(
            {"messages": initial_messages, "raw_query": raw_query},
            stream_mode="updates",
        ):
            for node_name, node_output in update.items():
                new_msgs = node_output.get("messages", [])
                all_messages.extend(new_msgs)
                self._message_manager.append_tool_call_message(chat_obj, node_name, new_msgs)
                await self._message_manager.save_chat(key, chat_obj)
    except Exception as e:
        error = str(e)
    return all_messages, error
```

`append_tool_call_message` inspects the agent node's output. If the last message has tool calls, it appends a `"Calling tool {name}"` message to the chat and saves to Redis. The tool names come from `AIMessage.tool_calls` — the LLM's actual decision. There is no hardcoded list of steps to announce.

### Polling on the frontend

The frontend uses recursive `setTimeout` instead of `setInterval`. This prevents poll requests from stacking up if a response is slow:

```typescript
async function schedulePoll(id: string) {
  const chat = await pollChat(id);

  const allAgentMessages = chat.content.filter((m) => m.actor === "Agent");
  const currentTurnMessages = allAgentMessages.slice(agentMessageOffsetRef.current);
  setMessages(currentTurnMessages);

  if (chat.agentStatus === "hasReplied") {
    endConversation();
    const finalMsg = [...chat.content].reverse().find((m) => m.agentStatus === "hasReplied");
    if (finalMsg && typeof finalMsg.text === "object") {
      setResult(finalMsg.text as ChatResult);
    }
    await stopChat(id);
    window.dispatchEvent(new CustomEvent("chat-completed"));
  } else if (chat.agentStatus === "isThinking") {
    pollTimeoutRef.current = setTimeout(() => schedulePoll(id), 2000);
  }
}
```

`agentMessageOffsetRef` tracks how many agent messages existed before the current turn started. Slicing from that offset means the tool-call log shows only messages from the ongoing turn.

A `Thinking…` indicator appears when consecutive polls return the same number of tool messages — meaning the agent is still processing but has not announced the next tool yet:

```typescript
const thinkingCount = currentTurnMessages.filter((m) => m.agentStatus === "isThinking").length;
setIsThinkingIdle(thinkingCount === prevThinkingCountRef.current);
prevThinkingCountRef.current = thinkingCount;
```

![Completed travel guide with narrative and place cards](./screenshot_2.png)

*The completed guide. Narrative at the top, place cards below — attraction, restaurant, hotel.*

---

## Step 6 — Multi-Turn Conversations

A single-turn agent is useful. A conversational agent is more powerful. The user should be able to say "what's in Melbourne?" and follow up with "for a weekend trip" without repeating the city.

### Pass history to the agent

The backend `continueChat` endpoint reads the full message history from Redis (active) or PostgreSQL (after stop), appends the new user message, and forwards everything to the AI agent:

```typescript
async continueChat(id: string, message: string): Promise<{ accepted: true }> {
  const cached = await this.redisService.getJson<ChatInterface>(`chat:${id}`);
  const existingMessages = cached
    ? cached.content
    : (await this.conversationRepo.findOne({ where: { uuid: id } })).content as ChatMessage[];

  const chatObject: ChatInterface = {
    id,
    title: cached?.title ?? null,
    content: [...existingMessages, { actor: ChatActor.user, text: message, timestamp: new Date() }],
    status: ChatStatus.isActive,
    agentStatus: AgentStatus.isThinking,
  };

  await this.redisService.setJson(`chat:${id}`, chatObject);
  this.agentService.call(id, message, existingMessages);  // full history passed
  return { accepted: true };
}
```

The AI agent reconstructs LangChain messages from the history. User turns become `HumanMessage`; completed agent replies (`agentStatus == "hasReplied"`) become `AIMessage`. Tool-call progress messages (`isThinking`) are skipped — they are UI state, not conversation context:

```python
@staticmethod
def build_messages(history: list, new_message: str) -> list:
    messages = []
    for msg in history:
        if msg.actor == "User":
            messages.append(HumanMessage(content=msg.text if isinstance(msg.text, str) else ""))
        elif msg.actor == "Agent" and msg.agentStatus == "hasReplied":
            text = msg.text.get("narrative", "") if isinstance(msg.text, dict) else msg.text
            messages.append(AIMessage(content=text))
    messages.append(HumanMessage(content=new_message))
    return messages
```

### Keep completed turns visible in the UI

When the user submits a follow-up, the frontend moves the current turn into a `completedTurns` array before resetting for the new one:

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
  agentMessageOffsetRef.current += messages.length;
  // reset current turn, call continueChat, start polling
}
```

Each completed turn renders its own tool-call log and results panel. Old turns stay visible above while the new one processes below.

### Reconstruct turns when loading from history

When a user opens a saved conversation, the flat `ChatMessage[]` must be split back into turns. Each `User` message starts a new turn; the agent messages following it belong to that turn until `agentStatus === "hasReplied"` closes it:

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
        const result = typeof msg.text === "object" ? msg.text as ChatResult : null;
        turns.push({ userMessage, agentMessages: [...agentMessages], result, error: null });
      }
    }
  }

  return turns;
}
```

All turns except the last go into `completedTurns`. The last turn populates current-turn state. `agentMessageOffsetRef` is set to the total number of agent messages in completed turns — so continuing from a loaded history gets the offset right automatically.

---

## Step 7 — Persist State

When the agent finishes, the backend persists the `ChatMessage[]` array to PostgreSQL:

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

Storing the message array directly — not a nested wrapper object — keeps the DB row clean. Everything including the full result payload for each agent turn lives inside `ChatMessage`. Nothing is split across columns.

The poll endpoint also writes to the DB opportunistically. When it detects `agentStatus === hasReplied` in Redis, it fires a background update so a page refresh never loses a completed reply, even if the user never explicitly triggers `stopChat`:

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

**ReAct over hardcoded pipeline.** A fixed `geocode → search → write` sequence is a workflow, not an agent. The LLM driving tool selection at runtime is what makes this an actual agent — it can handle errors from tool results, generalise to inputs the pipeline was not designed for, and skip tools that are not needed.

**`text: string | ChatContent` as the rendering contract.** The shape of `text` encodes the rendering intent — no separate discriminator field needed. `typeof text === "object"` means render as cards and narrative; string means plain text or error. This also keeps the DB column as proper typed JSON rather than a JSON string inside a JSON object.

**Result embedded in the message, not alongside it.** Putting the structured result inside the `hasReplied` message means the message array is the single source of truth. A multi-turn conversation with ten replies has ten self-contained result payloads — each visible in the flat DB row and reconstructable without joins or extra columns.

**`splitTurns` for history reconstruction.** A flat `ChatMessage[]` is the canonical format in both Redis and PostgreSQL. Splitting into turns is a pure function applied only when needed (loading history). The storage format never changes based on how many turns a conversation has.

**Redis over WebSockets.** Redis with polling is simpler to operate, easy to debug (`redis-cli get chat:{uuid}` shows exactly what state the agent is in), and scales without sticky sessions. For a 2-second poll interval the overhead is small.

**Fire-and-forget over synchronous execution.** Long-running agents must not block an HTTP connection. Returning a job ID immediately and letting the client poll is more resilient — the client can disconnect and reconnect without corrupting the agent's execution.

**`@cached_property` as the singleton mechanism.** One decorator replaces the `global _instance / if _instance is None` pattern. The `Container` class documents what gets constructed; the cache ensures it happens once.

**Constructor injection over module imports.** `ChatService(agent_graph, chat_manager, logger)` is explicit about what it needs. Swapping in a mock graph or mock Redis for tests does not require patching globals.

**Flat `ChatMessage[]` in PostgreSQL.** Storing the array directly in the `jsonb` column keeps the schema honest. Querying and debugging with `psql` operate on the same shape that the code uses.

---

## Source Code

```bash
git clone https://github.com/ngodinhloc/tourguide-agent.git
cd tourguide-agent
cp ai-agent/.env.example ai-agent/.env
# Add ANTHROPIC_API_KEY and GOOGLE_API_KEY to ai-agent/.env
docker-compose up --build
```

Open [http://localhost:3000](http://localhost:3000) and ask it about any city.
