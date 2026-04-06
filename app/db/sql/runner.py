"""
SQL Runner — executes parameterized queries safely.

Handles:
  - Per-query timeouts (statement_timeout)
  - Row limits with truncation detection
  - Read-only transaction enforcement
  - UUID → string coercion (psycopg2 doesn't handle UUID natively)
  - PII field masking before rows reach the LLM

This is the only place in the codebase that opens a DB connection for queries.
Import run_select() from here in your MCP server's data layer functions.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple
from uuid import UUID

from langfuse import observe

from app.utils.connect_db import get_conn


# ─── Type coercion ────────────────────────────────────────────────────────────
# psycopg2 passes UUIDs as Python UUID objects. Serialize them to strings
# so the JSON response the agent reads is clean.

def _adapt_value(v: Any) -> Any:
    if isinstance(v, UUID):
        return str(v)
    if isinstance(v, list):
        return [_adapt_value(x) for x in v]
    if isinstance(v, dict):
        return {k: _adapt_value(val) for k, val in v.items()}
    return v

def _adapt_params(params: Dict[str, Any]) -> Dict[str, Any]:
    return {k: _adapt_value(v) for k, v in params.items()}


# ─── PII masking ──────────────────────────────────────────────────────────────
# Mask sensitive fields before rows are returned to the MCP server and
# eventually read by the LLM. Add field names relevant to your schema.
#
# The LLM needs enough to answer the user's question — it rarely needs
# full email addresses, phone numbers, or raw UUIDs.

def _mask_email(v: str) -> str:
    if "@" not in v:
        return v
    local, domain = v.split("@", 1)
    if len(local) <= 2:
        return f"{local[0]}*@{domain}"
    return f"{local[0]}{'*' * (len(local) - 2)}{local[-1]}@{domain}"

def _mask_phone(v: str) -> str:
    digits = "".join(ch for ch in v if ch.isdigit())
    if not digits:
        return v
    return ("*" * max(0, len(digits) - 4)) + digits[-4:]

def _mask_id(v: str) -> str:
    s = str(v)
    return f"{s[:4]}…{s[-4:]}" if len(s) >= 8 else s

def _sanitize_value(key: str, v: Any) -> Any:
    if v is None:
        return None
    k = key.lower()
    if "email" in k and isinstance(v, str):
        return _mask_email(v)
    if ("phone" in k or "mobile" in k) and isinstance(v, str):
        return _mask_phone(v)
    if (k.endswith("_id") or k == "id") and isinstance(v, (str, UUID)):
        return _mask_id(str(v))
    return v

def sanitize_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Mask PII fields in every row before returning to caller."""
    return [{k: _sanitize_value(k, v) for k, v in row.items()} for row in rows]


# ─── Query runner ─────────────────────────────────────────────────────────────

@observe(name="sql.run_select")
def run_select(
    sql: str,
    params: Dict[str, Any],
    *,
    timeout_ms: int,
    max_rows: int,
) -> Tuple[List[Dict[str, Any]], bool]:
    """
    Execute a SELECT query and return (rows, truncated).

    Args:
        sql:        Parameterized SQL string using %(name)s placeholders.
        params:     Dict of parameter values. UUIDs are auto-adapted.
        timeout_ms: PostgreSQL statement_timeout in milliseconds.
                    Query is killed if it exceeds this. Prevents slow
                    queries from blocking the agent.
        max_rows:   Maximum rows to return. If more exist, truncated=True.
                    The MCP tool includes this in its response so the agent
                    knows to tell the user "showing first N results".

    Returns:
        (rows, truncated) — rows is a list of dicts (column → value),
        truncated is True if the result was cut off at max_rows.
    """
    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                # Per-query timeout — protects against runaway queries
                cur.execute("SET LOCAL statement_timeout = %s", (timeout_ms,))
                # Read-only — this layer never writes, enforced at DB level
                cur.execute("SET LOCAL TRANSACTION READ ONLY")

                cur.execute(sql, _adapt_params(params))

                cols = [d[0] for d in cur.description] if cur.description else []
                # Fetch one extra row to detect truncation without a COUNT query
                fetched = cur.fetchmany(max_rows + 1)
                truncated = len(fetched) > max_rows
                rows = [
                    {cols[i]: fetched[r][i] for i in range(len(cols))}
                    for r in range(min(len(fetched), max_rows))
                ]

        return sanitize_rows(rows), truncated
    finally:
        conn.close()
