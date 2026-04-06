# Architecture — MCP → LangChain → LangGraph

This document explains the full chain from your data source to the LLM agent,
so you know exactly where to plug in your own tools and databases.

---

## The Problem This Solves

LangChain agents expect tools in a specific format (`StructuredTool` with a
Pydantic args schema). MCP tools are defined on remote HTTP servers with their
own JSON schema format. This project bridges the two cleanly — your tools stay
as simple Python functions on an MCP server, and the agent sees them as native
LangChain tools with no manual conversion.

---

## Full Request Flow

```
User message
     │
     ▼
FastAPI router (app/routers/chat.py)
     │
     ▼
ChatService (app/services/chat.py)
     │  builds AgentState, calls graph
     ▼
LangGraph agent (app/graphs/fintech_graph.py)
     │
     ├─ safety_guard       → block identity probing attacks
     ├─ semantic_cache     → return cached answer if policy question seen before
     ├─ agent (GPT-4o)     → LLM decides which tools to call
     │       │
     │       ▼
     ├─ tools node         → executes MCP tool calls
     │       │
     │       │   HTTP POST /mcp
     │       ▼
     │  MCPMultiClient (app/integrations/mcp/core.py)
     │       │  routes by tool name → correct MCP server
     │       ▼
     │  MCP Server (MCP/server/data_server.py or vector_server.py)
     │       │  your data layer (_fetch_user_profile, _vector_search, etc.)
     │       ▼
     │  Your database / API
     │       │
     │       └─ result (dict) → JSON → ToolMessage → back to agent
     │
     └─ agent synthesizes final answer
```

---

## Layer 1 — MCP Servers (your tools live here)

**Files**: `MCP/server/data_server.py`, `MCP/server/vector_server.py`

Each `@mcp.tool()` function is a tool the agent can call:

```python
@mcp.tool()
def getUserProfile(user_id: str) -> dict:
    """Get a user's profile by their ID."""   # ← LLM reads this to decide when to call
    return _fetch_user_profile(user_id)       # ← your data layer
```

**What the framework does automatically:**
- The function's type annotations become a JSON schema (the agent uses this to know what args to send)
- `FastMCP` exposes the tool over HTTP as a stateless endpoint
- `LangfuseMCPTraceJoinMiddleware` links tool spans to the agent's Langfuse trace

**What you provide:**
- The `@mcp.tool()` function definitions (name, description, parameters)
- The data layer functions at the bottom (`_fetch_user_profile`, `_vector_search`, etc.)

**Adding a new tool:**
```python
@mcp.tool()
def getOrderHistory(user_id: str, limit: int = 10) -> dict:
    """List recent orders for a user."""
    # connect your orders DB here
    return {"user_id": user_id, "orders": [...], "count": N}
```
That's it. The agent discovers it automatically on startup.

---

## Layer 2 — MCP → LangChain Bridge (framework, don't change)

**Files**: `app/integrations/mcp/`

```
MCPMultiClient          (core.py)
    Calls list_tools() and call_tool() over HTTP for each server.
    Handles Langfuse trace header propagation.

MCPToolRegistry         (tool_registry.py)
    Converts MCP tool definitions → LangChain StructuredTools.
    Key steps:
      1. Fetch MCP tool list (name, description, inputSchema)
      2. Convert inputSchema (JSON Schema) → Pydantic model  [MCPHelper]
      3. Wrap call_tool() in a LangChain coroutine
      4. Return StructuredTool(name, description, args_schema, coroutine)

MCPHelper               (mcp_helper.py)
    _json_schema_to_pydantic()  — JSON Schema → Pydantic model
    sanitize_tool_name()        — makes names safe for LangChain
    parse_call_result()         — normalizes MCP response to MCPCallResult.text
```

**Why this matters:**
LangChain requires tools to have a Pydantic args schema so it can validate
the LLM's tool calls before executing them. MCP tools describe their inputs
in JSON Schema. `MCPHelper._json_schema_to_pydantic()` converts between the two
dynamically — you never write Pydantic models for your tools manually.

```
MCP inputSchema (JSON Schema):
{
  "type": "object",
  "properties": {
    "user_id": {"type": "string"},
    "limit":   {"type": "integer"}
  },
  "required": ["user_id"]
}

             ↓ MCPHelper._json_schema_to_pydantic()

Pydantic model (auto-generated):
class getUserProfile_Args(BaseModel):
    user_id: str
    limit:   Optional[int] = None
```

---

## Layer 3 — LangGraph Agent (orchestration)

**File**: `app/graphs/fintech_graph.py`

The agent is a LangGraph state machine. The tools from Layer 2 are bound to
the LLM at startup:

```python
tools = await tool_registry.get_tools()          # all StructuredTools
model = ChatOpenAI(model="gpt-4o").bind_tools(tools)  # LLM knows about them
```

When the LLM wants to call a tool, it emits a tool call in its response.
LangGraph's `tools` node intercepts it, calls the right `StructuredTool`,
gets the result, and feeds it back as a `ToolMessage`. The LLM then decides
whether to call another tool or produce the final answer.

**Agent state** (what persists across nodes):
```python
class AgentState(TypedDict):
    messages:      list[BaseMessage]   # full conversation history
    customer_id:   str                 # used to scope tool calls
    tool_rounds:   int                 # counts tool call loops (max 6)
    tool_cache:    dict                # in-session tool result cache
    blocked:       bool                # True if safety guard fired
    cache_hit:     bool                # True if served from Redis cache
    cached_response: str              # cached answer if cache_hit
```

**Tool result caching (in-session):**
Within one conversation turn, if the agent calls the same tool with the same
args twice, the second call is served from `tool_cache` without hitting the
MCP server. Key: `"{tool_name}:{json(args)}"`.

---

## Layer 4 — Semantic Cache (for knowledge-base queries)

**File**: `app/cache/semantic_cache.py`

Before calling the agent, the graph checks Redis for a semantically similar
previous answer:

```
Query → LLM classifier → POLICY?
                              ↓ yes
                         embed query (OpenAI)
                              ↓
                         Redis vector search (cosine distance < 0.05)
                              ↓ hit
                         return cached answer  ← skips agent entirely
                              ↓ miss
                         run agent → cache result if vector tools were used
```

This only activates for knowledge-base / policy questions (classified by a
fast `gpt-4o-mini` call). Personalized or follow-up questions always go to
the agent.

---

## Adding a New MCP Server

1. Create `MCP/server/my_server.py` (copy `data_server.py` as template)
2. Add a Dockerfile in `MCP/docker/Dockerfile.my_server`
3. Add the service to `docker/docker-compose.yml`
4. Register it in `app/integrations/mcp/core.py`:
   ```python
   def load_mcp_servers():
       return [
           MCPServerConfig(name="data",   url=os.getenv("MCP_DATA_URL", ...)),
           MCPServerConfig(name="vector", url=os.getenv("MCP_VECTOR_URL", ...)),
           MCPServerConfig(name="my",     url=os.getenv("MCP_MY_URL", ...)),  # ← add
       ]
   ```
5. Add `MCP_MY_URL=http://mcp-my:8053/mcp` to docker-compose environment

The agent discovers and loads the new tools automatically on next startup.

---

## Tool Design Guidelines

Patterns that work well for LLM-facing tools:

**1. Return focused, structured dicts** — not raw DB rows, not large blobs.
The LLM's context window is finite. Return only what's needed to answer.

**2. Descriptive docstrings** — the LLM reads the docstring to decide when
to call the tool. Be explicit about what it returns and when to use it.

**3. Consistent return shape** — use the same keys across similar tools
(`user_id`, `records`, `row_count`, `truncated`). The LLM pattern-matches.

**4. Enforce limits** — always accept a `limit` parameter and default to
something small (5–20). Never return unbounded results.

**5. Don't do retrieval AND synthesis in one tool** — split:
- Tool A: retrieve chunks
- Tool B: rerank chunks
- LLM: synthesize answer from chunks
This keeps each tool testable and lets the LLM skip reranking when confidence is high.

---

## SQL Query Patterns

### Non-vector (structured data lookup)

```python
@mcp.tool()
def getRecord(user_id: str, record_id: str) -> dict:
    """Look up a specific record by ID."""
    # psycopg2 / SQLAlchemy parameterized query
    # Return: {"id": ..., "field1": ..., "field2": ...}
```

Use for: account data, transaction history, user profiles — anything with
a known schema and direct key lookup.

### Vector (semantic / similarity search)

```python
@mcp.tool()
def retrieveChunks(query: str, top_k: int = 8) -> dict:
    """Search the knowledge base for chunks relevant to a query."""
    # 1. embed the query
    # 2. cosine similarity search in vector DB
    # 3. return top-K chunks with scores
```

Use for: FAQ lookup, policy search, documentation retrieval — anything where
you match by meaning, not by exact ID.

**Hybrid search** (what we used in the main project):
Combines dense (vector embedding) + sparse (BM25/keyword) scores to get the
best of both. pgvector supports this natively with the right setup.

```sql
SELECT id, text, source,
       (0.7 * (1 - embedding <=> $1::vector))   -- dense score
     + (0.3 * ts_rank(tsv, query))               -- sparse score
  AS hybrid_score
FROM document_chunks
ORDER BY hybrid_score DESC
LIMIT $2
```
