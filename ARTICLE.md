# Design and Build a Full-Stack AI Agent

This article walks through the design and implementation of a full-stack AI agent application, using a travel guide as the example. The agent receives a free-text location query and runs a ReAct loop — Claude decides which tools to call, reads the results, and keeps going until it has enough to write a response. Live progress streams to the browser as each tool is invoked, and multi-turn conversations are supported.

- User types a free-text location query in plain English.
- The agent runs a ReAct loop — it calls tools, reads the results, and decides what to do next.
- Claude writes a travel narrative based on the venues and returns a structured result.
- Follow-up queries like "what about for families?" continue the conversation — the agent carries the full context forward.

The focus is on the decisions that make this work in practice: how to structure a LangGraph ReAct agent across multiple services, how to expose tools via the MCP protocol, how to stream agent progress to the browser without WebSockets, and how to reconstruct multi-turn conversation history at the service boundary.

![Agent streaming tool calls and loading skeleton](./screenshot_1.png)

*The streaming tool-call log. Each tool the agent calls appears as a new line while the frontend polls every 2 seconds.*

---

## Architecture Overview

![Architecture overview](./architecture.png)

**Frontend** (Next.js 15, port 3000) — search bar, live tool-call log, and results panel. Polls `GET /api/chat/{id}` every 2 seconds while the agent is processing. Completed turns stay visible on screen as the conversation continues below. Left sidebar lists saved conversations and reloads them on click.

**Backend** (NestJS 11, port 8000) — REST chat API:
- `POST /api/chat/new` — create conversation in PostgreSQL + Redis, fire-and-forget to AI Agent, return `{ id }`
- `POST /api/chat/:id/cont` — append user message to history, fire-and-forget to AI Agent
- `GET /api/chat/:id` — return live chat from Redis, or persisted version from PostgreSQL
- `POST /api/chat/:id/stop` — persist `ChatMessage[]` to PostgreSQL, delete Redis key
- `GET /api/chat/history` — return all conversations (id, title, createdAt)

**AI Agent** (FastAPI + LangGraph, port 8001) — loads the current conversation from Redis, runs a LangGraph ReAct loop with Claude (`claude-sonnet-4-6`), and delegates all tool calls to the MCP server. The LLM decides which tools to call, in what order, and when it has enough to write a response. Agent progress is written to Redis after each node — the browser polls and displays each tool call as it happens. The protocol used to reach the MCP server is configurable via `MCP_PROTOCOL=MCP|REST`.

**MCP Server** (FastMCP + FastAPI, port 8002) — exposes `resolve_geocode` and `search_places` over two protocols: MCP (FastMCP's streamable HTTP at `POST /mcp/`) and REST (`POST /api/tool/call`). Owns the Google API keys; the AI Agent calls it without any direct access to the external APIs.

**Redis** — live chat state during agent processing, keyed by `chat:{uuid}`; shared by the backend and AI Agent so the browser can poll for real-time progress without WebSockets.

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

The agent supports two protocols — MCP and REST — selected by `MCP_PROTOCOL` at startup. Define an interface and let a factory pick the implementation.

Python has no `interface` keyword. `abc.ABC` enforces the contract at runtime — instantiating a subclass that skips `call()` raises `TypeError` immediately, which is stronger than a `Protocol` (type-checker only):

```python
class ToolClientInterface(ABC):
    @abstractmethod
    async def call(self, name: str, arguments: dict): ...

class McpTools(ToolClientInterface):
    async def call(self, name: str, arguments: dict):
        async with Client(self._url) as client:
            result = await client.call_tool(name, arguments)
            if result.content and isinstance(result.content[0], TextContent):
                return json.loads(result.content[0].text)
            return {}

class ToolClientFactory:
    def create(self) -> ToolClientInterface:
        if self._mcp_protocol == "MCP":
            return McpTools(self._mcp_server_url)
        return RestTools(self._mcp_server_url)
```

One subtlety with `McpTools`: FastMCP wraps non-dict returns (like `list[dict]`) in `structured_content` as `{"result": [...]}`. Reading `content[0].text` directly returns the original value as a JSON string — no unwrapping needed.

---

## Step 4 — Centralise Dependency Injection

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

`ChatService` receives everything through its constructor — it never imports `container` directly. The FastAPI router resolves from it via `Depends`.

---

## Step 5 — Decouple the Agent from the API Layer

An agent call can take 30–60 seconds. Holding an HTTP connection open for that duration is fragile and non-resumable. The fix is fire-and-forget — the backend persists the chat to Redis, fires the agent without awaiting it, and returns a conversation ID immediately:

```typescript
await this.redisService.setJson(`chat:${id}`, chatObject);
this.agentService.call(id, message, []);  // no await
return { id };
```

The client polls `GET /api/chat/{id}` and sees agent progress as it writes to Redis. If the client disconnects and reconnects, it picks up from wherever the agent stopped — state is in Redis, not in memory.

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

The frontend uses recursive `setTimeout` (not `setInterval`) to avoid stacking polls when a response is slow. `agentMessageOffsetRef` slices the agent message list to show only the current turn's tool calls — completed turns keep their own log visible above.

![Completed travel guide with narrative and place cards](./screenshot_2.png)

*The completed guide. Narrative at the top, place cards below — attraction, restaurant, hotel.*

---

## Step 8 — Multi-Turn Conversations

The backend passes the full `ChatMessage[]` history to the agent on each follow-up. The agent reconstructs LangChain messages from it — user turns become `HumanMessage`, completed replies become `AIMessage`. Tool-call progress messages (`isThinking`) are skipped — they are UI state, not conversation context:

```python
for msg in history:
    if msg.actor == "User":
        messages.append(HumanMessage(content=msg.text))
    elif msg.actor == "Agent" and msg.agentStatus == "hasReplied":
        text = msg.text.get("narrative", "") if isinstance(msg.text, dict) else msg.text
        messages.append(AIMessage(content=text))
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

The poll endpoint also writes to PostgreSQL opportunistically — when it detects `agentStatus === hasReplied` in Redis it fires a background `update`, so a page refresh never loses a completed reply even if `stopChat` is never called.

---

## Key Design Decisions

**ReAct over hardcoded pipeline.** A fixed `geocode → search → write` sequence is a workflow, not an agent. The LLM driving tool selection at runtime is what makes this an actual agent — it can handle errors from tool results, generalise to inputs the pipeline was not designed for, and skip tools that are not needed.

**MCP server as a separate service.** The agent does not call Google APIs directly. Extracting tool implementations into a dedicated MCP server means the agent owns no API keys, the tools are callable from any MCP-compatible client, and both protocols (MCP and REST) are available on the same endpoints. The `MCP_PROTOCOL` env var lets you switch between them without code changes.

**`ToolClientInterface` as an ABC, not a Protocol.** Python's `abc.ABC` enforces the interface at runtime — instantiating a subclass that doesn't implement `call()` raises `TypeError` immediately. A `Protocol` is only checked by type checkers. For a contract that must hold at startup, ABC is the right choice.

**Always read `content[0].text`, not `structured_content`.** FastMCP wraps non-dict returns (like `list[dict]`) into `structured_content` as `{"result": [...]}`. The `content[0].text` field always contains the raw serialized value — using it directly avoids the wrapping and keeps the parsing logic simple.

**`text: string | ChatContent` as the rendering contract.** The shape of `text` encodes the rendering intent — no separate discriminator field needed. `typeof text === "object"` means render as cards and narrative; string means plain text or error. This also keeps the DB column as proper typed JSON rather than a JSON string inside a JSON object.

**Result embedded in the message, not alongside it.** Putting the structured result inside the `hasReplied` message means the message array is the single source of truth. A multi-turn conversation with ten replies has ten self-contained result payloads — each visible in the flat DB row and reconstructable without joins or extra columns.

**`splitTurns` for history reconstruction.** A flat `ChatMessage[]` is the canonical format in both Redis and PostgreSQL. Splitting into turns is a pure function applied only when needed (loading history). The storage format never changes based on how many turns a conversation has.

**Redis over WebSockets.** Redis with polling is simpler to operate, easy to debug (`redis-cli get chat:{uuid}` shows exactly what state the agent is in), and scales without sticky sessions. For a 2-second poll interval the overhead is small.

**Fire-and-forget over synchronous execution.** Long-running agents must not block an HTTP connection. Returning a job ID immediately and letting the client poll is more resilient — the client can disconnect and reconnect without corrupting the agent's execution.

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
