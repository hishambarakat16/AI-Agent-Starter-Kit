"""
MCP Data Server — Template for any data source (SQL, REST API, MongoDB, etc.)

This file shows the PATTERN for exposing your data as MCP tools that a
LangGraph agent can call. The framework code (FastMCP, Langfuse tracing,
tool registration) is already wired up. Your job is to fill in the data
layer at the bottom.

How it connects to the agent:
  data_server.py (FastMCP tools)
       ↓  HTTP POST /mcp
  MCPServerClient  (app/integrations/mcp/core.py)
       ↓  MCPCallResult.text (JSON string)
  MCPToolRegistry  (app/integrations/mcp/tool_registry.py)
       ↓  StructuredTool (LangChain format)
  LangGraph agent  (app/graphs/fintech_graph.py)
       ↓  tool result injected as ToolMessage
  LLM decides next step
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional
from datetime import date

from mcp.server.fastmcp import FastMCP
from langfuse import get_client

from MCP.server.env import get_host, get_port
from MCP.server.langfuse_trace_middleware import LangfuseMCPTraceJoinMiddleware
from MCP.server.logging_config import configure_logging
from .mcp_trace_context import get_trace_context

# ── Uncomment once you've implemented app/db/sql/ for your schema ──
# from app.db.sql.service import run_data_tool
# from app.db.sql.schemas import (
#     GetRecordRequest, ListRecordsRequest,
#     ListRecordsDatedRequest, GetSummaryRequest,
# )

configure_logging(
    config_path=Path(__file__).resolve().parent / "logging.yaml",
    logs_dir=Path("logs/mcp"),
)
logger = logging.getLogger("mcp_data")

# ─── FastMCP setup ────────────────────────────────────────────────────────────
# stateless_http=True means each tool call is a fresh HTTP request.
# No persistent connections, no server state — easy to scale.
mcp = FastMCP(
    name="data-tools",
    host=get_host(),
    port=get_port(8051),
    stateless_http=True,
)
_inner_app = mcp.streamable_http_app()
app = LangfuseMCPTraceJoinMiddleware(_inner_app)  # joins Langfuse trace from agent


# ─── Tool definitions ─────────────────────────────────────────────────────────
# Each @mcp.tool() function becomes a tool the agent can call.
# The function signature (parameter names + type annotations) is automatically
# converted into a JSON schema that LangChain uses to validate agent tool calls.
# The docstring becomes the tool description the LLM reads to decide when to use it.

@mcp.tool()
def getUserProfile(user_id: str) -> dict:
    """
    Get a user's profile by their ID.

    Returns: dict with user fields (id, name, email, created_at, etc.)
    """
    logger.info("getUserProfile user_id=%s", user_id)
    input_echo = {"user_id": user_id}

    langfuse = get_client()
    trace_context = get_trace_context()  # joins the agent's Langfuse trace

    with langfuse.start_as_current_observation(
        as_type="span", name="mcp:getUserProfile",
        trace_context=trace_context, input=input_echo
    ) as span:
        result = _fetch_user_profile(user_id)
        span.update(output=result)
        return result


@mcp.tool()
def listUserRecords(
    user_id: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    limit: int = 10,
) -> dict:
    """
    List records for a user, optionally filtered by date range.

    Args:
        user_id:    The user's ID. (required)
        start_date: Filter records from this date (YYYY-MM-DD). Optional.
        end_date:   Filter records up to this date (YYYY-MM-DD). Optional.
        limit:      Max number of records to return. Default 10.

    Returns: dict with keys: user_id, records (list), row_count, truncated.
    """
    logger.info("listUserRecords user_id=%s start=%s end=%s limit=%d", user_id, start_date, end_date, limit)
    input_echo = {
        "user_id": user_id,
        "start_date": start_date.isoformat() if start_date else None,
        "end_date": end_date.isoformat() if end_date else None,
        "limit": limit,
    }

    langfuse = get_client()
    trace_context = get_trace_context()

    with langfuse.start_as_current_observation(
        as_type="span", name="mcp:listUserRecords",
        trace_context=trace_context, input=input_echo
    ) as span:
        result = _fetch_user_records(user_id, start_date, end_date, limit)
        span.update(output={"row_count": result.get("row_count", 0)})
        return result


@mcp.tool()
def getSummary(user_id: str) -> dict:
    """
    Get an aggregated summary for a user (totals, averages, counts, etc.)

    Returns: dict with summary fields relevant to your domain.
    """
    logger.info("getSummary user_id=%s", user_id)
    input_echo = {"user_id": user_id}

    langfuse = get_client()
    trace_context = get_trace_context()

    with langfuse.start_as_current_observation(
        as_type="span", name="mcp:getSummary",
        trace_context=trace_context, input=input_echo
    ) as span:
        result = _fetch_summary(user_id)
        span.update(output=result)
        return result


# ─── YOUR DATA LAYER ──────────────────────────────────────────────────────────
# Replace these functions with your actual database / API calls.
# The tool functions above call these — keep the separation clean.
#
# Patterns that work well here:
#   - psycopg2 / asyncpg for PostgreSQL
#   - SQLAlchemy ORM for any relational DB
#   - pymongo for MongoDB
#   - httpx for external REST APIs
#   - boto3 for DynamoDB
#
# Return plain dicts — they are serialized to JSON and sent back to the agent.
# Keep responses focused: the LLM's context window is finite.

def _fetch_user_profile(user_id: str) -> dict:
    """Replace with your DB/API call."""
    raise NotImplementedError(
        "Connect your data source here. "
        "Return a dict, e.g.: {'id': user_id, 'name': '...', 'email': '...'}"
    )


def _fetch_user_records(
    user_id: str,
    start_date: Optional[date],
    end_date: Optional[date],
    limit: int,
) -> dict:
    """
    Replace with your DB/API call.
    Return format the agent expects:
      {
        "user_id": user_id,
        "records": [...],       # list of dicts
        "row_count": N,
        "truncated": bool       # True if more records exist beyond limit
      }
    """
    raise NotImplementedError("Connect your data source here.")


def _fetch_summary(user_id: str) -> dict:
    """Replace with your aggregation query or API call."""
    raise NotImplementedError("Connect your data source here.")


# ─── Example: PostgreSQL with psycopg2 ───────────────────────────────────────
# Uncomment and adapt if using PostgreSQL:
#
# import os
# import psycopg2
# import psycopg2.extras
#
# def _get_conn():
#     return psycopg2.connect(
#         host=os.getenv("POSTGRES_HOST", "localhost"),
#         port=int(os.getenv("POSTGRES_PORT", 5432)),
#         dbname=os.getenv("POSTGRES_DB"),
#         user=os.getenv("POSTGRES_USER"),
#         password=os.getenv("POSTGRES_PASSWORD"),
#     )
#
# def _fetch_user_profile(user_id: str) -> dict:
#     with _get_conn() as conn:
#         with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
#             cur.execute(
#                 "SELECT id, name, email, created_at FROM users WHERE id = %s",
#                 (user_id,)
#             )
#             row = cur.fetchone()
#             if not row:
#                 return {"error": f"User {user_id} not found"}
#             return dict(row)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
