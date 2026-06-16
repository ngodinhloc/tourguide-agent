# Frontend — Agent Instructions

Next.js 16 / React 19 / Tailwind CSS 4 app. Proxies all `/api/*` requests to the backend at `API_TARGET` (port 8000 in dev).

## Stack

- **Next.js 16** with App Router (`src/app/`)
- **React 19** — use Server Components by default; add `"use client"` only where interactivity is required
- **Tailwind CSS 4** — utility-first, no component library
- **TypeScript 5** — strict mode

## Key files

```
src/
  app/
    layout.tsx          Root layout
    page.tsx            Home page
  components/           UI components (client or server)
  lib/api.ts            Fetch wrapper — all backend calls go through here
  types/tour.ts         Shared TypeScript interfaces
```

## API proxy

`next.config.ts` rewrites `/api/*` → `http://{API_TARGET}/api/*`. Never call the backend URL directly from components — always use relative `/api/` paths.

## Patterns

- Data fetching: use `fetch` in Server Components or `lib/api.ts` in Client Components
- Polling: use `setInterval` + `fetch` in a Client Component; clear the interval when `agentStatus === 'hasReplied'`
- State: prefer local `useState`; reach for context only when state crosses multiple layout levels

## Dev commands

```bash
npm install
npm run dev       # http://localhost:3000
npm run build
npm run lint
```

## Environment

```
NODE_ENV=development
API_TARGET=http://localhost:8000
```
