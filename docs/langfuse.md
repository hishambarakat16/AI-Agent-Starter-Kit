# Langfuse Observability Guide

Langfuse gives you a full trace for every user message — which tools were called, what the LLM said, how long each step took, and what it cost. Without it you're guessing when something goes wrong.

---

## What Gets Traced

Every layer of the agent is instrumented:

```
User message
     │
     ▼
[Trace starts]
     │
     ├── semantic_cache_lookup  → hit/miss + latency
     │
     ├── LLM call (agent)       → input tokens, output tokens, model, latency, cost
     │
     ├── tool call: data_getUserProfile
     │     └── MCP server round-trip latency
     │
     ├── tool call: vector_retrieveChunks
     │     └── MCP server round-trip latency
     │
     ├── LLM call (agent, round 2) → synthesize final answer
     │
     └── [Trace ends] — total tokens, total cost, total latency
```

Each trace is linked to a session, so you can see the full conversation history across turns.

---

## Setup

### 1. Get your keys

Sign up at [cloud.langfuse.com](https://cloud.langfuse.com) — the free tier is enough for development. Create a project and copy the keys from the project settings.

### 2. Add to `.env`

```bash
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=https://cloud.langfuse.com
```

For self-hosted Langfuse, change `LANGFUSE_HOST` to your instance URL.

### 3. Start the stack

```bash
docker-compose -f docker/docker-compose.yml up --build
```

Traces will appear in Langfuse within a few seconds of the first message.

---

## How Tracing Is Wired

The tracing is set up in two places:

**LLM calls** — LangChain's `CallbackHandler` is used. The `LangfuseCallbackHandler` is passed directly to the graph invocation, so every LLM call inside LangGraph is automatically captured with token counts and latency.

**MCP tool calls** — each MCP server runs a `LangfuseMCPTraceJoinMiddleware`. When the agent calls a tool, the middleware reads the `X-Langfuse-Trace-Id` header (injected by the agent runner), creates a child span on the same trace, and records the tool name, input, output, and duration. This is what links the tool call latency to the parent LLM trace.

```
Agent runner
  │  sets X-Langfuse-Trace-Id on every HTTP request to MCP servers
  ▼
MCP server middleware
  │  reads the header → creates child span on the parent trace
  ▼
Tool result returned
  │
  └── Trace in Langfuse shows: LLM call → tool span → LLM call
```

---

## Session Feedback

After each message, users can submit thumbs up/down feedback. This is linked to the Langfuse trace for that message, letting you filter traces by user satisfaction:

```bash
curl -X POST http://localhost:8000/v1/chat/session/<id>/feedback \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"feedback_type": "thumbs_up", "message_id": "<message_uuid>"}'
```

In Langfuse, go to a trace → Scores to see the feedback attached.

---

## What to Look at in Langfuse

**Traces view** — one row per user message. Sort by latency to find slow responses. Filter by session to see a full conversation.

**Scores** — filter by `thumbs_down` to find responses users didn't like. Click through to the trace to see which tools were called and what the LLM said.

**Cost dashboard** — total token spend by model, by day. Useful for estimating production costs before scaling.

**Sessions** — group traces by session to replay a full conversation with all tool calls expanded.

---

## What Langfuse Does NOT Do Here

- It does not host the LLM — it only observes calls you make to OpenAI
- It does not store your data — it stores trace metadata (inputs, outputs, token counts, latency)
- It is not required for the agent to work — if `LANGFUSE_PUBLIC_KEY` is missing or wrong, the agent runs normally but traces are silently dropped

For full Langfuse documentation see [langfuse.com/docs](https://langfuse.com/docs).

---

## Relevant Files

| File | What it does |
|---|---|
| `app/services/agent_runner.py` | Sets up `LangfuseCallbackHandler`, injects trace ID into MCP headers |
| `MCP/server/langfuse_trace_middleware.py` | Reads trace ID header, creates child spans for MCP tool calls |
| `app/routers/chat.py` | Attaches `trace_id` to message responses (used by feedback endpoint) |
