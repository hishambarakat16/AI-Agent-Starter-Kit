# LangGraph Agent Starter

A production-ready template for building AI agents that can query your own data and documents. Built with LangGraph, FastAPI, and MCP (Model Context Protocol).

Clone it, connect your database, and have a working agent in one `docker-compose up`.

---

## What You Get

- **Multi-turn chat agent** — GPT-4o with tool calling, conversation memory, and context summarization
- **MCP tool servers** — plug in any data source (SQL, REST API, vector DB) as independent HTTP services
- **Semantic cache** — Redis-backed response cache that matches questions by meaning, not exact text
- **JWT authentication** — login, token validation, per-user session isolation
- **Rate limiting + timeouts** — production-safe middleware, configured per endpoint
- **Langfuse tracing** — every LLM call, tool call, and cache hit visible in one trace
- **SQL query framework** — parameterized queries, per-action row limits, timeouts, PII masking
- **Vector search framework** — hybrid dense+sparse search, score normalization, optional reranking

---

## How It Works

```
User message
     │
     ▼
FastAPI  →  LangGraph agent
                 │
                 ├── safety_guard        block prompt injection attacks
                 ├── semantic_cache      return cached answer if seen before
                 │
                 ├── agent (GPT-4o)      decide which tools to call
                 │        │
                 │        ▼
                 └── tools node
                          │
              ┌───────────┴───────────┐
              ▼                       ▼
     mcp-data (port 8051)    mcp-vector (port 8052)
     your SQL / API           your vector DB
              │                       │
              └───────────┬───────────┘
                          ▼
                  result → agent → final answer
                                        │
                                        ▼
                               cache if knowledge-base query
```

The key insight: **your tools run as separate HTTP services** (MCP servers). The agent calls them by name — it doesn't know or care what database they're talking to. Swap the implementation without touching the agent.

---

## Prerequisites

- Docker Desktop (or Docker Engine + Compose v2)
- OpenAI API key (`gpt-4o` access)
- Langfuse account — [cloud.langfuse.com](https://cloud.langfuse.com) (free tier works)

---

## Quick Start

### 1. Copy the environment file

```bash
cp .env.example .env
```

Fill in the required values:

```bash
# .env
POSTGRES_USER=postgres
POSTGRES_PASSWORD=yourpassword
POSTGRES_DB=myapp

REDIS_URL=redis://localhost:6378        # for local dev; Docker sets this automatically

JWT_SECRET_KEY=your-secret-32-char-minimum-key
OPENAI_API_KEY=sk-...

LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=https://cloud.langfuse.com

REQUEST_TIMEOUT_SECONDS=60
SEMANTIC_CACHE_DISTANCE_THRESHOLD=0.05
```

### 2. Start everything

```bash
docker-compose -f docker/docker-compose.yml up --build
```

This starts:

| Service | Port | What it does |
|---|---|---|
| `api` | 8000 | FastAPI application (the agent lives here) |
| `postgres` | 5432 | PostgreSQL with pgvector extension |
| `redis` | 6378 | Redis Stack (semantic cache + rate limiting) |
| `mcp-data` | 8051 | Your data/SQL tool server |
| `mcp-vector` | 8052 | Your vector search tool server |

### 3. Verify it's running

```bash
curl http://localhost:8000/health
# → {"status": "ok"}
```

### 4. Get a token and chat

```bash
# Login
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=user@example.com&password=yourpassword"

# Create a session
curl -X POST http://localhost:8000/v1/chat/session \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{}'

# Send a message
curl -X POST http://localhost:8000/v1/chat/session/<session_id>/message \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"content": "Hello, what can you help me with?"}'
```

---

## Connecting Your Data

This is the main thing you need to do. There are two tool servers to fill in.

### Data tools (SQL / API)

**File:** `MCP/server/data_server.py`

This is where you define tools that fetch structured data — user records, orders, account info, anything with a known schema.

Each `@mcp.tool()` function becomes a tool the agent can call. The function signature is automatically converted to a JSON schema that the agent uses.

```python
@mcp.tool()
def getUserProfile(user_id: str) -> dict:
    """Get a user's profile by their ID."""
    return _fetch_user_profile(user_id)   # ← your DB call here
```

Then fill in the data layer at the bottom of the file:

```python
def _fetch_user_profile(user_id: str) -> dict:
    # Example with PostgreSQL:
    with _get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, name, email FROM users WHERE id = %s",
                (user_id,)
            )
            return dict(cur.fetchone())
```

**The SQL framework** (`app/db/sql/`) gives you patterns for doing this cleanly:

```
app/db/sql/
  queries.py   — parameterized query functions → (sql, params) tuples
  runner.py    — execute safely: timeout, row limit, PII masking
  schemas.py   — Pydantic request/response models with discriminated unions
  actions.py   — per-action policy (max_rows, statement_timeout_ms)
  service.py   — dispatch table: action → query fn → typed response
```

See `app/db/sql/queries.py` for examples of optional filters, date ranges, and aggregations. See `app/db/sql/runner.py` for why `%(param)s` placeholders matter (SQL injection prevention).

### Vector / RAG tools

**File:** `MCP/server/vector_server.py`

This is where you define tools for semantic search — FAQs, documentation, policy documents, anything where the user asks questions in natural language.

Three tools are pre-defined:

| Tool | What it does |
|---|---|
| `rewriteQuery` | Rephrase the user's question for better retrieval |
| `retrieveChunks` | Vector similarity search → top-K chunks |
| `rerankChunks` | Optional: re-score chunks by relevance |

The agent calls them in sequence to answer knowledge-base questions. The `signals.suggest_rerank` flag in the retrieve response tells the agent whether reranking is worth the extra latency.

**The vector framework** (`app/db/vector/`) gives you the full retrieval stack:

```
app/db/vector/
  models.py    — DocumentHit, DocumentFilters, RerankConfig
  queries.py   — dense_search, sparse_search, hybrid_search (pgvector)
  rerank.py    — trigger logic, HTTP reranker backend, graceful fallback
  retriever.py — orchestrates search + rerank, embedding cache
```

`DocumentRetriever` is already wired into `vector_server.py` — you just need to point it at your chunk table.

---

## The MCP → LangChain Bridge

This is the framework's core value — it's what makes your Python functions callable by the agent without any manual LangChain tool code.

```
Your function (data_server.py)
     │  @mcp.tool() registers it with FastMCP
     ▼
FastMCP exposes it as HTTP POST /mcp
     │
     ▼
MCPServerClient  (app/integrations/mcp/core.py)
     │  calls session.call_tool(name, args) over HTTP
     ▼
MCPHelper._json_schema_to_pydantic()  (app/integrations/mcp/mcp_helper.py)
     │  converts MCP inputSchema (JSON Schema) → Pydantic model automatically
     ▼
MCPToolRegistry.get_tools()  (app/integrations/mcp/tool_registry.py)
     │  wraps everything in a LangChain StructuredTool
     ▼
model.bind_tools(tools)  (app/graphs/fintech_graph.py)
     │  GPT-4o sees the tool and knows when/how to call it
     ▼
Agent calls tool → result injected as ToolMessage → agent continues
```

**What this means for you:** write a normal Python function with type annotations and a docstring. The rest is handled. No LangChain tool boilerplate, no schema writing.

### Adding a new tool

1. Add a function to `MCP/server/data_server.py` (or `vector_server.py`):

```python
@mcp.tool()
def getOrderStatus(order_id: str) -> dict:
    """Get the current status and estimated delivery date for an order."""
    # your DB/API call
    return {"order_id": order_id, "status": "shipped", "eta": "2024-03-15"}
```

2. Restart the `mcp-data` container — the agent discovers it automatically.

### Adding a new MCP server

1. Create `MCP/server/my_server.py` (copy `data_server.py` as template)
2. Add a Dockerfile in `MCP/docker/`
3. Add the service to `docker/docker-compose.yml`
4. Register it in `app/integrations/mcp/core.py`:

```python
def load_mcp_servers():
    return [
        MCPServerConfig(name="data",   url=os.getenv("MCP_DATA_URL", ...)),
        MCPServerConfig(name="vector", url=os.getenv("MCP_VECTOR_URL", ...)),
        MCPServerConfig(name="orders", url=os.getenv("MCP_ORDERS_URL", ...)),  # ← new
    ]
```

---

## Semantic Cache

The agent caches responses to knowledge-base questions in Redis. The next time someone asks a semantically similar question, it returns the cached answer instantly — no LLM call, no tool calls.

```
"What is your return policy?"   → cache MISS → agent answers → stored
"How do I return an item?"      → cache HIT  → same answer returned immediately
"What's the refund process?"    → cache HIT  → same answer returned immediately
```

**How similar is "similar enough"?** Controlled by `SEMANTIC_CACHE_DISTANCE_THRESHOLD` in `.env`:
- `0.05` (default) — strict, only very close paraphrases match
- `0.15` — looser, more hits but risk of serving a slightly wrong answer

**When it doesn't cache:**
The LLM classifier marks queries as `PERSONALIZED` (asking about the user's own data) — those always go to the agent. You never want to cache "what's my balance?" and serve it to another user.

**Redis Stack is required** — not plain Redis. The semantic cache needs the `RedisSearch` module for vector index creation. Plain `redis:alpine` boots fine but crashes at runtime when the cache initializes. The docker-compose uses `redis/redis-stack-server:latest` which includes it.

**Clear the cache:**
```bash
docker exec agent-redis redis-cli KEYS "qa_cache:*" | xargs docker exec -i agent-redis redis-cli DEL
```

---

## Project Structure

```
├── app/
│   ├── main.py                     FastAPI entry point, middleware stack
│   ├── auth/                       JWT token creation and validation
│   ├── cache/
│   │   └── semantic_cache.py       Redis semantic cache (lookup + store)
│   ├── db/
│   │   ├── sql/                    SQL query framework
│   │   │   ├── queries.py          ← parameterized query functions
│   │   │   ├── runner.py           ← safe execution (timeout, limit, PII mask)
│   │   │   ├── schemas.py          ← request/response Pydantic models
│   │   │   ├── actions.py          ← per-action policy (max_rows, timeout_ms)
│   │   │   └── service.py          ← dispatch table
│   │   └── vector/                 Vector search framework
│   │       ├── models.py           ← DocumentHit, filters, config
│   │       ├── queries.py          ← dense, sparse, hybrid search (pgvector)
│   │       ├── rerank.py           ← trigger logic + reranker backends
│   │       └── retriever.py        ← orchestrator with embedding cache
│   ├── graphs/
│   │   ├── fintech_graph.py        LangGraph agent state machine
│   │   └── llm_gaurd.py            Identity probing guard
│   ├── integrations/mcp/           MCP → LangChain bridge (don't modify)
│   │   ├── core.py                 MCPMultiClient, server loader
│   │   ├── tool_registry.py        MCP tools → LangChain StructuredTools
│   │   └── mcp_helper.py           JSON Schema → Pydantic, name sanitization
│   ├── middleware/
│   │   └── timeout.py              60s request timeout (bilingual errors)
│   ├── routers/                    HTTP layer (auth, chat, health)
│   ├── schemas/                    Pydantic request/response models
│   └── services/                   Business logic (chat, agent runner)
│
├── MCP/
│   ├── server/
│   │   ├── data_server.py          ← YOUR data tools go here
│   │   └── vector_server.py        ← YOUR vector tools go here
│   └── docker/                     Dockerfiles per MCP server
│
├── docker/
│   ├── docker-compose.yml          Full stack (5 services)
│   ├── Dockerfile                  API image
│   └── initdb/                     PostgreSQL init scripts (schema + pgvector)
│
├── scripts/
│   └── backfill_app_users.py       Seed app users from existing data
│
├── .env.example                    Copy to .env and fill in
└── ARCHITECTURE.md                 Full technical deep dive
```

---

## API Reference

All endpoints except `/health` and `/auth/login` require `Authorization: Bearer <token>`.

### Auth

| Method | Endpoint | Rate limit | Body |
|---|---|---|---|
| `POST` | `/auth/login` | 5/min | `username=...&password=...` (form) |

### Chat

| Method | Endpoint | Rate limit | Description |
|---|---|---|---|
| `POST` | `/v1/chat/session` | 10/min | Create session |
| `POST` | `/v1/chat/session/{id}/message` | 20/min | Send message |
| `POST` | `/v1/chat/session/{id}/message:stream` | 20/min | Send message (SSE stream) |
| `POST` | `/v1/chat/session/{id}/feedback` | 20/min | Thumbs up/down |
| `DELETE` | `/v1/chat/session/{id}` | 10/min | Delete session |

### Health

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Returns `{"status": "ok"}` |

---

## Production Notes

**Rate limits** are per IP, sliding window. Adjust in the router files.

**Timeout** defaults to 60 seconds. Change with `REQUEST_TIMEOUT_SECONDS` in `.env`. The Uvicorn `--timeout-keep-alive 65` in docker-compose is intentionally 5 seconds longer — gives the app time to return a proper timeout response before the connection drops.

**Workers** are set to 1 for development. For production, increase in docker-compose:
```yaml
command: uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4 ...
```

**Redis memory** is capped at 512MB with `allkeys-lru` eviction. The cache loses old entries gracefully when full — the agent just re-answers the question and re-caches it.

**Langfuse** is optional but strongly recommended. Without it you're flying blind on what the agent is doing, how much it costs, and where it's slow.

---

## Learn More

- `ARCHITECTURE.md` — full technical explanation of the MCP→LangChain→agent chain, tool design guidelines, SQL vs vector query patterns
- `app/integrations/mcp/mcp_helper.py` — how JSON Schema becomes a Pydantic model
- `app/graphs/fintech_graph.py` — the full LangGraph state machine with comments
- `app/db/vector/queries.py` — dense, sparse, and hybrid SQL patterns explained
