# app/MCP/sql_server.py
from __future__ import annotations

import logging
from uuid import UUID
from pathlib import Path
from datetime import date
from typing import Optional
from mcp.server.fastmcp import FastMCP
from langfuse import observe

from MCP.server.langfuse_trace_middleware import LangfuseMCPTraceJoinMiddleware
from MCP.server.logging_config import configure_logging
configure_logging( config_path=Path(__file__).resolve().parent / "logging.yaml",logs_dir=Path("logs/mcp"))

logger = logging.getLogger("mcp_sql")


from .env import get_host, get_port
from app.sql.sql_service import run_sql_tool
from app.sql.schemas import (
    GetCustomerProfileRequest,
    ListAccountsRequest,
    GetAccountSummaryRequest,
    ListTransactionsRequest,
)
from .mcp_trace_context import get_trace_context
from langfuse import get_client


mcp = FastMCP(
    name="account-tools",
    host=get_host(),
    port=get_port(8051),
    stateless_http=True,
)


# app = mcp.streamable_http_app()
_inner_app = mcp.streamable_http_app()

app = LangfuseMCPTraceJoinMiddleware(_inner_app)

@mcp.tool()
def getCustomerProfile(customer_id: UUID):
    """
    Get a customer profile by customer_id.

    Returns: SQLToolResponse (action, customer_id, rows, row_count, truncated, meta).
    """
    logger.info("sql getCustomerProfile input customer_id=%s", customer_id)

    input_echo = {"customer_id": str(customer_id)}

    langfuse = get_client()
    trace_context = get_trace_context()

    with langfuse.start_as_current_observation(as_type="span", name="LangGraph", trace_context=trace_context, input=input_echo) as span:
        req = GetCustomerProfileRequest(action="get_customer_profile", customer_id=customer_id)
        resp = run_sql_tool(req)
        out = resp.model_dump(mode="json")

        span.update(output={"row_count": out.get("row_count", 0), "truncated": out.get("truncated"), "result": out})
        logger.info("sql getCustomerProfile output rows=%d", out.get("row_count", 0))
        return out
    

@mcp.tool()
def listAccounts(customer_id: UUID):
    """
    List all accounts for a customer.

    Returns: SQLToolResponse (action, customer_id, rows, row_count, truncated, meta).
    """
    logger.info("sql listAccounts input customer_id=%s", customer_id)

    input_echo = {"customer_id": str(customer_id)}

    langfuse = get_client()
    trace_context = get_trace_context()

    with langfuse.start_as_current_observation(as_type="span", name="LangGraph", trace_context=trace_context, input=input_echo) as span:
        req = ListAccountsRequest(action="list_accounts", customer_id=customer_id)
        resp = run_sql_tool(req)
        out = resp.model_dump(mode="json")

        span.update(output={"row_count": out.get("row_count", 0), "truncated": out.get("truncated"), "result": out})
        logger.info("sql listAccounts output rows=%d", out.get("row_count", 0))
        return out

@mcp.tool()
def getAccountSummary(customer_id: UUID):
    """
    Get summary stats per account (or a single account if account_id is provided).

    Returns: SQLToolResponse (action, customer_id, rows, row_count, truncated, meta).
    """
    logger.info("sql getAccountSummary in customer_id=%s", customer_id)

    input_echo = {"customer_id": str(customer_id)}

    langfuse = get_client()
    trace_context = get_trace_context()

    with langfuse.start_as_current_observation(as_type="span", name="LangGraph", trace_context=trace_context, input=input_echo) as span:
        req = GetAccountSummaryRequest(action="get_account_summary", customer_id=customer_id)
        resp = run_sql_tool(req)
        out = resp.model_dump(mode="json")

        span.update(output={"row_count": out.get("row_count", 0), "truncated": out.get("truncated"), "result": out})
        logger.info("sql getAccountSummary out row_count=%s truncated=%s", resp.row_count, resp.truncated)
        return out
    

@mcp.tool()
def listTransactions(
    customer_id: UUID,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    limit: int = 5,
):
    """
    List transactions for a customer, optionally filtered by account_id and date range.
    you need to provide an INT limit, and the default is 5, so try to send 5 if you dont know how many to send

    Returns: SQLToolResponse (action, customer_id, rows, row_count, truncated, meta).
    """
    logger.info("sql listTransactions in customer_id=%s start_date=%s end_date=%s limit=%d",customer_id, start_date, end_date, limit)

    input_echo = {
        "customer_id": str(customer_id),
        "start_date": start_date.isoformat() if start_date else None,
        "end_date": end_date.isoformat() if end_date else None,
        "limit": int(limit),
    }

    langfuse = get_client()
    trace_context = get_trace_context()

    with langfuse.start_as_current_observation(as_type="span", name="LangGraph", trace_context=trace_context, input=input_echo) as span:
        req = ListTransactionsRequest(
            action="list_transactions",
            customer_id=customer_id,
            start_date=start_date,
            end_date=end_date,
            limit=int(limit),
        )
        resp = run_sql_tool(req)
        out = resp.model_dump(mode="json")

        span.update(output={"row_count": out.get("row_count", 0), "truncated": out.get("truncated"), "result": out})
        logger.info("sql listTransactions out row_count=%s truncated=%s", resp.row_count, resp.truncated)
        return out


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
