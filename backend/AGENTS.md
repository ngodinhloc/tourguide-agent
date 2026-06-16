# Backend — Agent Instructions

NestJS 11 API that manages chat conversations. It owns state (PostgreSQL + Redis) and delegates AI processing to the ai-agent service via fire-and-forget HTTP calls.

## Stack

- **NestJS 11** — modules, controllers, services
- **TypeORM 0.3** — PostgreSQL, `synchronize: true` in dev (no migration files)
- **ioredis 5** — Redis client, global `RedisService`
- **@nestjs/axios** — HTTP calls to ai-agent
- **class-validator / class-transformer** — DTO validation via global `ValidationPipe`

## Module structure

```
src/
  app.module.ts
  main.ts
  chat/
    contracts/
      chat.interface.ts       ChatInterface, ChatMessage, ChatStatus, AgentStatus, ChatActor
    controllers/
      chat.controller.ts      POST /api/chat/new · POST /api/chat/:id/cont
                              POST /api/chat/:id/stop · GET /api/chat/:id
    services/
      chat.service.ts         Business logic — reads/writes PostgreSQL + Redis
      agent.service.ts        Fire-and-forget POST to ai-agent /api/chat
    dto/
      new-chat.dto.ts         { message: string }
      continue-chat.dto.ts    { message: string }
    interfaces/               (legacy — use contracts/ instead)
  database/
    database.module.ts        TypeORM root configuration
    entities/
      conversation.entity.ts  uuid, title, content (jsonb), createdAt, updatedAt
  redis/
    redis.module.ts           @Global() module
    services/
      redis.service.ts        getJson<T> / setJson / del
  health/
    controllers/
      health.controller.ts    GET /api/health → { status: 'ok' }
```

## Redis key convention

`chat:{uuid}` → JSON-serialised `ChatInterface`

The key is written by the NestJS backend and updated in place by the ai-agent as it streams progress. `stopChat` deletes the key after persisting to PostgreSQL.

## ChatInterface shape (canonical — defined in `contracts/chat.interface.ts`)

```typescript
enum ChatStatus  { active, stopped }
enum AgentStatus { isThinking, hasReplied }
enum ChatActor   { user = 'User', agent = 'Agent' }

interface ChatMessage  { actor: ChatActor; text: string; timestamp: Date }
interface ChatInterface {
  id: string; title?: string | null;
  content: ChatMessage[]; status: ChatStatus; agentStatus?: AgentStatus
}
```

## Async AI call pattern

`AgentService.call(id, message)` fires a non-blocking `.subscribe()` on the Axios Observable — the HTTP request is sent but the NestJS endpoint returns 202 immediately. Never `await` inside `call`.

## Environment

```
PORT=8000
DATABASE_URL=postgresql://tourguide:tourguide@localhost:5432/tourguide
REDIS_URL=redis://localhost:6379
AI_AGENT_URL=http://localhost:8001
CORS_ORIGINS=http://localhost:3000
```

## Dev commands

```bash
npm install
npm run start:dev   # http://localhost:8000 with watch mode
npm run build
npm run lint
```
