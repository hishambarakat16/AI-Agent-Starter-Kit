# MCP Tools Guide

MCP (Model Context Protocol) is how you give the agent access to your data. You write a Python function, and the framework automatically makes it callable by the LLM — no LangChain boilerplate, no schema writing.

---

## The Core Idea

```
Your Python function  →  MCP server (HTTP)  →  LangChain tool  →  Agent
```

Each `@mcp.tool()` function becomes:
1. An HTTP endpoint the MCP server exposes
2. A LangChain `StructuredTool` the agent can call
3. A tool the LLM sees in its context, with name, description, and typed parameters

The conversion from your function signature to a JSON schema (and then to a Pydantic model the agent validates against) happens automatically in `app/integrations/mcp/mcp_helper.py`.

---

## Defining a Tool

Open `MCP/server/data_server.py` and add a function:

```python
@mcp.tool()
def getOrderStatus(order_id: str, include_history: bool = False) -> dict:
    """
    Get the current status of an order.

    Args:
        order_id:        The order ID to look up. (required)
        include_history: If True, include status change history. Default False.

    Returns:
        dict with status, estimated_delivery, and optionally history.
    """
    return _fetch_order_status(order_id, include_history)
```

Three things matter:
- **Type annotations** — become the JSON schema the agent uses to validate its tool call
- **Default values** — make parameters optional (agent can omit them)
- **Docstring** — the LLM reads this to decide when and how to call the tool

Then implement the data layer at the bottom of the file:

```python
def _fetch_order_status(order_id: str, include_history: bool) -> dict:
    # connect to your DB / API here
    ...
```

Restart the `mcp-data` container — the agent discovers the new tool automatically on next startup.

---

## The MCP → LangChain Bridge (how it works)

This is the framework's core. You don't need to change it, but understanding it helps.

```
@mcp.tool() function
        │
        │  FastMCP reads the type annotations and generates:
        ▼
MCP inputSchema (JSON Schema):
{
  "type": "object",
  "properties": {
    "order_id":        { "type": "string" },
    "include_history": { "type": "boolean" }
  },
  "required": ["order_id"]
}
        │
        │  MCPHelper._json_schema_to_pydantic()  [app/integrations/mcp/mcp_helper.py]
        ▼
Auto-generated Pydantic model:
class getOrderStatus_Args(BaseModel):
    order_id: str
    include_history: Optional[bool] = None
        │
        │  MCPToolRegistry.get_tools()  [app/integrations/mcp/tool_registry.py]
        ▼
LangChain StructuredTool(
    name="data_getOrderStatus",
    description="Get the current status of an order...",
    args_schema=getOrderStatus_Args,
    coroutine=<async wrapper that calls the MCP server>
)
        │
        │  model.bind_tools(tools)
        ▼
GPT-4o sees the tool and knows when/how to call it
```

---

## Adding a New MCP Server

If you want a completely separate server (e.g. an orders server alongside the existing data server):

**1. Create the server file**

```python
# MCP/server/orders_server.py
from mcp.server.fastmcp import FastMCP
from MCP.server.env import get_host, get_port
from MCP.server.langfuse_trace_middleware import LangfuseMCPTraceJoinMiddleware

mcp = FastMCP(name="orders", host=get_host(), port=get_port(8053), stateless_http=True)
_inner_app = mcp.streamable_http_app()
app = LangfuseMCPTraceJoinMiddleware(_inner_app)

@mcp.tool()
def listOrders(user_id: str, limit: int = 10) -> dict:
    """List recent orders for a user."""
    ...
```

**2. Add a Dockerfile**

Copy `MCP/docker/Dockerfile.sql` to `MCP/docker/Dockerfile.orders` and update the module path.

**3. Add to docker-compose**

```yaml
mcp-orders:
  build:
    context: ..
    dockerfile: MCP/docker/Dockerfile.orders
  ports:
    - "8053:8053"
  environment:
    - MCP_HOST=0.0.0.0
    - MCP_PORT=8053
    - PYTHONPATH=/workspace
  command: uv run uvicorn MCP.server.orders_server:app --host 0.0.0.0 --port 8053
```

**4. Register it in the loader**

```python
# app/integrations/mcp/core.py
def load_mcp_servers():
    return [
        MCPServerConfig(name="data",   url=os.getenv("MCP_DATA_URL", ...)),
        MCPServerConfig(name="vector", url=os.getenv("MCP_VECTOR_URL", ...)),
        MCPServerConfig(name="orders", url=os.getenv("MCP_ORDERS_URL", "http://mcp-orders:8053/mcp")),
    ]
```

**5. Add to `.env`**

```bash
MCP_ORDERS_URL=http://localhost:8053/mcp   # for local dev
```

The agent now sees all tools from all three servers on next startup.

---

## Tool Design Tips

**Return focused dicts, not raw DB rows.** The LLM's context window is limited. Return only what's needed to answer the question — not entire tables.

**Write descriptive docstrings.** The LLM reads the docstring to decide when to call the tool. Be explicit: "Use this to look up X. Do NOT use this for Y."

**Always include a `limit` parameter.** Never return unbounded results. Default to something small (5–20).

**Keep tools single-purpose.** Don't retrieve AND summarize in one tool. Let the LLM call `retrieve` then synthesize. This makes each tool testable and lets the LLM skip steps when it already has the info.

**Consistent return shape.** Use the same keys across similar tools (`user_id`, `records`, `row_count`, `truncated`). The LLM pattern-matches on structure.

---

## Relevant Files

| File | What it does |
|---|---|
| `MCP/server/data_server.py` | Your structured data tools — edit this |
| `MCP/server/vector_server.py` | Your vector/RAG tools — edit this |
| `app/integrations/mcp/core.py` | Server registry — add new servers here |
| `app/integrations/mcp/tool_registry.py` | Converts MCP tools → LangChain StructuredTools |
| `app/integrations/mcp/mcp_helper.py` | JSON Schema → Pydantic, name sanitization, response parsing |
| `app/integrations/mcp/models.py` | `MCPServerConfig`, `MCPCallResult`, `MCPToolRef` |
