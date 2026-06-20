# Agentic AI: Building an Event-Driven Agent with LangGraph and MCP

This article walks through the design and implementation of a full-stack agentic AI application, using a travel guide as the example. A user types a free-text location query, and the agent runs a ReAct loop — Claude decides which tools to call, reads the results, and keeps reasoning until it has enough to write a response. Live progress streams to the browser as each tool is invoked. Follow-up queries like "what about for families?" continue the conversation, with the agent carrying the full context forward.

The focus is on the decisions that make this work in practice: 
- How to structure a LangGraph ReAct agent across multiple services
- Hw to expose tools via the MCP protocol
- How to decouple services with a message broker
- How to stream agent progress to the browser in real time via WebSockets
- How to reconstruct multi-turn conversation history at the service boundary.

![Agent streaming tool calls and loading skeleton](./screenshot_1.png)

*The streaming tool-call log. Each tool call appears in real time via WebSocket as the agent works.*

---

## Architecture Overview

![Architecture overview](./architecture.png)

**Frontend** (Next.js 15, port 3000) — search bar, live tool-call log, and results panel. Opens a WebSocket to `ws://localhost:8000/ws` and receives real-time `chat-update` events as the agent works. Completed turns stay visible on screen as the conversation continues below. Left sidebar lists saved conversations and reloads them on click.

**Backend** (NestJS 11, port 8000) — REST chat API:
- `POST /api/chat/new` — create conversation in PostgreSQL + Redis, publish `ChatEvent` to RabbitMQ, return `{ id }`
- `POST /api/chat/:id/cont` — append user message to history, publish `ChatEvent` to RabbitMQ
- `GET /api/chat/:id` — return live chat from Redis, or persisted version from PostgreSQL
- `POST /api/chat/:id/stop` — persist `ChatMessage[]` to PostgreSQL, delete Redis key
- `GET /api/chat/history` — return all conversations (id, title, createdAt)

**RabbitMQ** — message broker between the backend and the AI agent. The backend publishes a `ChatEvent` (conversation ID, message, history) to the durable `tour-guide.chat` queue. The AI agent subscribes and processes events one at a time.

**AI Agent** (FastAPI + LangGraph, port 8001) — subscribes to the `tour-guide.chat` RabbitMQ queue. For each event, loads the current conversation from Redis, runs a LangGraph ReAct loop with Claude (`claude-sonnet-4-6`), and delegates all tool calls to the MCP server via `McpClient`. Agent progress is written to Redis after each node — the backend pushes each update to the browser in real time via WebSocket.

**MCP Server** (FastMCP + FastAPI, port 8002) — exposes `resolve_geocode` and `search_places` over the MCP protocol (FastMCP's streamable HTTP at `POST /mcp/`). Owns the Google API keys; the AI Agent calls it without any direct access to the external APIs.

**Redis** — live chat state during agent processing, keyed by `chat:{uuid}`; shared by the backend and AI Agent. The backend's WebSocket gateway polls Redis at 500 ms and pushes `chat-update` events to subscribed browser clients.

**PostgreSQL** — persistent store; written when a conversation starts and again when it stops (full `ChatMessage[]`). History and reload reads come from here.

---

## Step 1 — Build a Real ReAct Agent

A hardcoded pipeline (`geocode → search → write`) is a workflow, not an agent. LangGraph's ReAct pattern gives the model control: agent node calls the LLM → LLM emits tool calls → tools node executes them → back to agent. The loop continues until the LLM replies with no tool calls.

The conditional edge drives the loop. `_should_continue` checks the last message — if it has tool calls, route to tools; otherwise end:

```python
graph.add_conditional_edges("agent", self._should_continue, {"tools": "tools", "end": END})
graph.add_edge("tools", "agent")

@staticmethod
def _should_continue(state: AgentState) -> str:
    last = state["messages"][-1]
    if isinstance(last, AIMessage) and last.tool_calls:
        return "tools"
    return "end"
```

The LLM decides which tools to call at runtime. The graph just loops until it stops.

---

## Step 2 — Separate Tools into an MCP Server

The tools own the Google API keys. Keeping those keys in the AI agent couples two concerns — agent logic and external API access. Extracting them into a dedicated MCP server means the agent owns no keys, and the tools are callable by any MCP-compatible client.

MCP (Model Context Protocol) is a JSON-RPC standard for connecting LLMs to tools. FastMCP makes registration a single decorator:

```python
fast_mcp = FastMCP("Tour Guide MCP Server")

@fast_mcp.tool()
async def resolve_geocode(query: str) -> dict:
    """Resolve a free-text travel query to a canonical place name and GPS coordinates."""
    return await container.geocoding_tool.resolve(query)
```

FastMCP needs its lifespan wired to the parent FastAPI app — it initialises a session manager task group on startup. Without it, requests fail with a `Task group is not initialized` error:

```python
_mcp_app = fast_mcp.http_app(path="/")
app = FastAPI(lifespan=_mcp_app.lifespan)
app.mount("/mcp", _mcp_app)
```

`path="/"` tells FastMCP to serve at the root of the mounted sub-app — without it, Starlette redirects `/mcp` → `/mcp/` and the sub-app returns 404.

---

## Step 3 — Call the MCP Server from the Agent

The agent calls the MCP server via `McpClient`, which wraps FastMCP's `Client` over streamable HTTP. One subtlety: FastMCP wraps non-dict returns (like `list[dict]`) in `structured_content` as `{"result": [...]}`. Reading `content[0].text` directly returns the original value as a JSON string — no unwrapping needed:

```python
class McpClient:
    def __init__(self, mcp_server_url: str):
        self._url = f"{mcp_server_url}/mcp/"

    async def call(self, name: str, arguments: dict):
        async with Client(self._url) as client:
            result = await client.call_tool(name, arguments)
            if result.content and isinstance(result.content[0], TextContent):
                return json.loads(result.content[0].text)
            return {}
```

The `@tool` functions in `tools.py` delegate directly to `McpClient` — no factory or protocol toggle needed:

```python
_client = McpClient(settings.mcp_server_url)

@tool
async def resolve_geocode(query: str) -> dict:
    """Resolve a free-text travel query to a canonical place name and GPS coordinates."""
    return await _client.call("resolve_geocode", {"query": query})
```

---

## Step 4 — Decouple Services with RabbitMQ

An agent call can take 30–60 seconds. Coupling the backend directly to the AI agent via HTTP creates two problems: a long-lived connection that is fragile to restarts, and tight availability coupling — if the agent is slow to start, backend calls fail.

The fix is a message broker. The backend publishes a `ChatEvent` to a durable RabbitMQ queue and returns a conversation ID immediately. The AI agent subscribes independently and processes each event when it is ready:

```typescript
// backend: publish and return immediately
publish(event: ChatEvent): void {
  this.channel.sendToQueue(
    'tour-guide.chat',
    Buffer.from(JSON.stringify(event)),
    { persistent: true },
  );
}
```

```python
# ai-agent: subscribe and process
async def start(self) -> None:
    connection = await aio_pika.connect_robust(self._url)
    channel = await connection.channel()
    queue = await channel.declare_queue(QUEUE, durable=True)
    async with queue.iterator() as messages:
        async for message in messages:
            async with message.process():
                await self._event_handler.handle(message)
```

The queue is durable and messages are persistent — if the agent restarts mid-processing, unacknowledged messages are requeued. `message.process()` acts as a context manager: it ACKs the message if the block completes without error, and NACKs (requeues) if an exception is raised.

The AI agent startup wires the consumer as a background asyncio task via FastAPI's lifespan:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(container.rabbitmq_consumer.start())
    yield
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
```

---

## Step 5 — Centralise Dependency Injection

Both the AI agent and the MCP server use a `Container` class with `@cached_property` to wire dependencies. The first access constructs the object; every subsequent access returns the cached instance — no global variables, no `if _instance is None` guards:

```python
class Container:
    @cached_property
    def agent_graph(self):
        return AgentGraph().build()

    @cached_property
    def chat_service(self) -> ChatService:
        return ChatService(
            agent_graph=self.agent_graph,
            chat_manager=self.chat_manager,
            logger=self.logger("chat_service"),
        )

container = Container()
```

The event pipeline follows the same pattern — `RabbitMQConsumer`, `ChatEventHandler`, and `ChatService` are all wired through the container with injected dependencies:

```python
@cached_property
def rabbitmq_consumer(self) -> RabbitMQConsumer:
    return RabbitMQConsumer(
        rabbitmq_url=settings.rabbitmq_url,
        event_handler=self.chat_event_handler,
        logger=self.logger("rabbitmq_consumer"),
    )
```

---

## Step 6 — Type the Message Contract

`ChatMessage.text` is either a plain string (tool call announcements, errors) or a `ChatContent` object (the final reply). The type of `text` is the rendering contract — no discriminator field needed:

```typescript
interface ChatMessage {
  actor: "User" | "Agent";
  text: string | ChatContent;   // string = status/error, object = render cards
  agentStatus?: "isThinking" | "hasReplied" | null;
}
```

The frontend uses `typeof` to decide how to render — no `JSON.parse`, no extra fields:

```typescript
if (finalMsg && typeof finalMsg.text === "object") {
  setResult(finalMsg.text);   // → ResultsPanel (narrative + place cards)
} else {
  setError(finalMsg?.text as string);
}
```

---

## Step 7 — Stream State to the UI

LangGraph's `stream_mode="updates"` emits a dict per node completion. After each agent node, the tool names from `AIMessage.tool_calls` are written to Redis as `"Calling tool {name}"` messages — before the tools node even executes:

```python
async for update in self._graph.astream(..., stream_mode="updates"):
    for node_name, node_output in update.items():
        new_msgs = node_output.get("messages", [])
        all_messages.extend(new_msgs)
        self._message_manager.append_tool_call_message(chat_obj, node_name, new_msgs)
        await self._message_manager.save_chat(key, chat_obj)
```

The frontend connects to `ws://localhost:8000/ws` and sends `{ event: "subscribe", data: chatId }`. The backend's `ChatGateway` polls Redis at 500 ms for that chat key and pushes `{ event: "chat-update", data: ChatInterface }` to the client on every change. When `agentStatus === "hasReplied"` arrives, the gateway stops polling and the client closes the connection. `agentMessageOffsetRef` slices the agent message list to show only the current turn's tool calls — completed turns keep their own log visible above.

![Completed travel guide with narrative and place cards](./screenshot_2.png)

*The completed guide. Narrative at the top, place cards below — attraction, restaurant, hotel.*

---

## Step 8 — Multi-Turn Conversations

The backend passes the full `ChatMessage[]` history to the agent on each follow-up via the `ChatEvent` payload. The agent reconstructs LangChain messages from it — user turns become `HumanMessage`, completed replies become `AIMessage`. Tool-call progress messages (`isThinking`) are skipped — they are UI state, not conversation context. Only the narrative is passed as the prior `AIMessage`; the full `ChatContent` object (with its place list) stays in history as a `dict` and is available to the service layer:

```python
for msg in history:
    if msg.actor == "User":
        messages.append(HumanMessage(content=msg.text))
    elif msg.actor == "Agent" and msg.agentStatus == "hasReplied":
        text = msg.text.get("narrative", "") if isinstance(msg.text, dict) else msg.text
        messages.append(AIMessage(content=text))
```

The system prompt instructs the LLM to check whether place data already exists in conversation history before calling any tools:

```
If the conversation already contains place data for the relevant destination:
- Do NOT call resolve_geocode or search_places again.
- Reuse the existing places from the conversation history.
- Rewrite the narrative to fit the new angle (e.g. "for a weekend", "for families").

If place data for the destination is not yet available:
1. Call resolve_geocode → 2. Call search_places → 3. Write narrative.
```

Because the LLM only returns a new narrative (not a new place list), `ChatService` falls back to the `places` and `location` from the most recent `hasReplied` message in history whenever no tools were called:

```python
if not places:
    for msg in reversed(request.history):
        if msg.actor == "Agent" and msg.agentStatus == "hasReplied" and isinstance(msg.text, dict):
            places = msg.text.get("places", [])
            location_name = msg.text.get("location", location_name)
            break
```

On the frontend, a `splitTurns` function splits the flat `ChatMessage[]` back into turns when loading a saved conversation. Each `User` message starts a new turn; `agentStatus === "hasReplied"` closes it. All turns except the last go into `completedTurns` — old results stay visible above as the new turn processes below.

---

## Step 9 — Persist State

When the agent finishes, the frontend calls `POST /api/chat/:id/stop`. The backend reads from Redis and writes the flat `ChatMessage[]` directly into a `jsonb` column — no wrapper, no joins:

```typescript
async stopChat(id: string): Promise<{ stopped: true }> {
  const current = await this.redisService.getJson<ChatInterface>(`chat:${id}`);
  await this.conversationRepo.save({ uuid: id, content: current.content });
  await this.redisService.del(`chat:${id}`);
  return { stopped: true };
}
```

The stop endpoint also writes to PostgreSQL opportunistically — when it detects `agentStatus === hasReplied` in Redis it persists the full `ChatMessage[]`, so a page refresh never loses a completed reply even if `stopChat` was delayed.

---

## Key Design Decisions

**ReAct over hardcoded pipeline.** A fixed `geocode → search → write` sequence is a workflow, not an agent. The LLM driving tool selection at runtime is what makes this an actual agent — it can handle errors from tool results, generalise to inputs the pipeline was not designed for, and skip tools that are not needed.

**RabbitMQ over HTTP for agent dispatch.** Calling the AI agent via HTTP creates tight coupling — a slow agent restart means the backend returns errors. Publishing a durable message to a queue decouples availability: the backend always succeeds immediately, and the agent processes the message when it is ready. Durable queues with persistent messages also survive restarts without losing work.

**MCP server as a separate service.** The agent does not call Google APIs directly. Extracting tool implementations into a dedicated MCP server means the agent owns no API keys and the tools are callable from any MCP-compatible client. The MCP protocol (JSON-RPC over streamable HTTP) is the sole interface — no REST fallback needed.

**`ConsumerMessage` as a `typing.Protocol`.** The RabbitMQ consumer handler receives a `ConsumerMessage` (a structural type with `body: bytes`) rather than `aio_pika.IncomingMessage`. This keeps the handler layer free of the AMQP library, making it testable without a real queue.

**Always read `content[0].text`, not `structured_content`.** FastMCP wraps non-dict returns (like `list[dict]`) into `structured_content` as `{"result": [...]}`. The `content[0].text` field always contains the raw serialized value — using it directly avoids the wrapping and keeps the parsing logic simple.

**`text: string | ChatContent` as the rendering contract.** The shape of `text` encodes the rendering intent — no separate discriminator field needed. `typeof text === "object"` means render as cards and narrative; string means plain text or error. This also keeps the DB column as proper typed JSON rather than a JSON string inside a JSON object.

**Result embedded in the message, not alongside it.** Putting the structured result inside the `hasReplied` message means the message array is the single source of truth. A multi-turn conversation with ten replies has ten self-contained result payloads — each visible in the flat DB row and reconstructable without joins or extra columns.

**`splitTurns` for history reconstruction.** A flat `ChatMessage[]` is the canonical format in both Redis and PostgreSQL. Splitting into turns is a pure function applied only when needed (loading history). The storage format never changes based on how many turns a conversation has.

**WebSocket delivery over HTTP polling.** The browser opens a WebSocket to `/ws` and subscribes by sending a chat ID. The backend gateway polls Redis at 500 ms per subscription and pushes each change — no client-side timers, no wasted requests when nothing has changed. Redis remains the shared state store between the AI agent and the backend, easy to inspect (`redis-cli get chat:{uuid}`) and shared without sticky sessions.

**Tool reuse across multi-turn conversations.** The LLM's system prompt instructs it to skip `resolve_geocode` and `search_places` when place data for the destination is already present in conversation history, rewriting the narrative only. Because the LLM returns only a new narrative (not a new place list), `ChatService` fills in the places and location from the most recent `hasReplied` message in history as a fallback. The result is always complete — fresh narrative, correct place cards — with no redundant API calls and no extra latency.

**`@cached_property` as the singleton mechanism.** One decorator replaces the `global _instance / if _instance is None` pattern. The `Container` class documents what gets constructed; the cache ensures it happens once.

---

## Source Code

```bash
git clone https://github.com/ngodinhloc/tourguide-agent.git
cd tourguide-agent
cp ai-agent/.env.example ai-agent/.env
cp mcp-server/.env.example mcp-server/.env
# Add ANTHROPIC_API_KEY to ai-agent/.env
# Add GOOGLE_API_KEY to mcp-server/.env
docker-compose up --build
```

Open [http://localhost:3000](http://localhost:3000) and ask it about any city.
