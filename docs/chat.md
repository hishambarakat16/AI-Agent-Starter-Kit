# Chat Interface Guide

This guide explains how the chat system works end to end — sessions, message storage, the agent loop, context management, and streaming.

---

## Session Model

Every conversation lives in a **session**. Sessions are:
- Scoped to a user (you can only access your own sessions)
- Identified by a UUID
- Stored in memory (not in the database — see [Storage](#storage) below)

```
User
 │
 ├── Session A (uuid)
 │     ├── Message 1 (user)
 │     ├── Message 2 (assistant)
 │     └── Message 3 (user)
 │
 └── Session B (uuid)
       └── Message 1 (user)
```

A session also carries a `customer_id` — this is the ID the agent uses when calling data tools. It ensures the agent only fetches data for the logged-in user's customer record, not arbitrary IDs.

---

## Request Flow

```
POST /v1/chat/session/{id}/message  { "content": "What's my balance?" }
         │
         ▼
  ChatService (app/services/chat.py)
         │  validates session ownership
         │  loads session history from ChatMemoryStore
         │  calls AgentRunner
         ▼
  AgentRunner (app/services/agent_runner.py)
         │  builds AgentState with messages + customer_id
         │  invokes LangGraph graph
         ▼
  LangGraph (app/graphs/fintech_graph.py)
         │
         ├── safety_guard       → block if identity probing detected
         ├── semantic_cache     → return cached answer if policy question seen before
         ├── agent (GPT-4o)     → decide which tools to call
         ├── tools              → call MCP servers, inject results as ToolMessages
         └── agent (again)      → synthesize final answer
         │
         ▼
  Response stored in ChatMemoryStore
  Response returned to user
```

---

## Storage

Messages are stored **in memory** using `ChatMemoryStore` (`app/repository/chat_store.py`). This means:

- Fast — no DB round-trips for message history
- Sessions are lost if the server restarts
- Suitable for demos and development; for production replace with a persistent store (PostgreSQL, Redis, etc.)

The in-memory store structure:

```python
{
  "session_id": [list of ChatMessageResponse],
  ...
}

# Ownership map (prevents cross-user access)
{
  "session_id": "user@example.com",
  ...
}

# Customer ID map (used by agent for tool calls)
{
  "session_id": "customer-uuid",
  ...
}
```

To switch to persistent storage, implement the same interface in `app/repository/chat.py` and back it with a database.

---

## Context Management

Long conversations would eventually overflow the LLM's context window. The agent handles this automatically:

**Summarization** — after `SUMMARIZE_THRESHOLD` turns (default 12), the agent compresses old messages into a single summary using `gpt-4o-mini`, keeping only the most recent `SUMMARIZE_KEEP_RECENT` messages (default 6) in full.

**Topic change detection** — after `CLEAR_CHECK_MIN_HUMAN_TURNS` turns (default 3), a fast LLM check decides whether the user has switched topics. If yes, old messages are cleared to keep the context focused.

Both thresholds are configurable at the top of `app/graphs/fintech_graph.py`.

---

## Tool Round Limit

The agent can call tools multiple times per message (e.g. fetch profile → fetch transactions → synthesize). The loop is capped at `max_tool_rounds = 6` to prevent runaway chains. After 6 rounds the agent is forced to produce an answer with whatever information it has.

---

## Streaming

Send a message with streaming (SSE) via the `:stream` endpoint:

```bash
curl -X POST http://localhost:8000/v1/chat/session/<id>/message:stream \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"content": "What are my recent transactions?"}'
```

The response is a stream of `data:` events:

```
data: {"type": "token", "content": "Your "}
data: {"type": "token", "content": "last "}
data: {"type": "token", "content": "5 transactions..."}
data: {"type": "done"}
```

Cached responses also stream token by token so the UI behaviour is identical whether the answer came from the agent or the cache.

---

## Feedback

After a message, users can submit thumbs up/down feedback. This is linked to the Langfuse trace for that message, so you can see which responses users found helpful:

```bash
curl -X POST http://localhost:8000/v1/chat/session/<id>/feedback \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"feedback_type": "thumbs_up", "message_id": "<message_uuid>"}'
```

`feedback_type` accepts `thumbs_up` or `thumbs_down`.

---

## Relevant Files

| File | What it does |
|---|---|
| `app/routers/chat.py` | HTTP routes — session CRUD, message, stream, feedback |
| `app/services/chat.py` | Business logic — session ownership, message dispatch |
| `app/services/agent_runner.py` | Invokes the LangGraph graph, handles streaming |
| `app/repository/chat_store.py` | In-memory session and message store |
| `app/repository/chat.py` | Repository interface — swap this for a DB-backed implementation |
| `app/graphs/fintech_graph.py` | LangGraph state machine — the full agent loop |
| `app/schemas/chat.py` | Request/response Pydantic models |
