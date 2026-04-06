"""
SQL Service — dispatches tool requests to the right query and packages results.

This is the layer that MCP server tools call. It:
  1. Validates the request has an allowed action
  2. Applies per-action policy (max_rows, timeout)
  3. Builds the SQL query
  4. Runs it via runner.run_select()
  5. Validates rows into typed Pydantic models
  6. Returns a typed response the MCP tool serializes to JSON

Adding a new action:
  1. Add it to DataAction enum in schemas.py
  2. Add a request + response model in schemas.py
  3. Write the query function in queries.py
  4. Add an ActionPolicy entry in actions.py
  5. Add an _ActionSpec entry in _ACTION_SPECS below
"""
from __future__ import annotations

from typing import Any, Callable, Dict, NamedTuple, Tuple, Type

from langfuse import observe

from .actions import ACTION_POLICIES
from .queries import (
    q_get_record,
    q_get_summary,
    q_list_records,
    q_list_records_by_date,
)
from .runner import run_select
from .schemas import (
    DataAction,
    DataToolRequest,
    DataToolResponse,
    GetRecordRequest,
    GetRecordResponse,
    GetSummaryRequest,
    GetSummaryResponse,
    ListRecordsDatedRequest,
    ListRecordsDatedResponse,
    ListRecordsRequest,
    ListRecordsResponse,
    RecordRow,
    SummaryRow,
)


class _ActionSpec(NamedTuple):
    build: Callable[[Any], Tuple[str, Dict[str, Any]]]  # (req) → (sql, params)
    row_model: Type
    resp_model: Type


# ─── Action dispatch table ────────────────────────────────────────────────────
# Maps each action to: how to build the query, what row model to validate
# results against, and what response model to return.

_ACTION_SPECS: Dict[DataAction, _ActionSpec] = {
    DataAction.get_record: _ActionSpec(
        build=lambda req: q_get_record(req.record_id),
        row_model=RecordRow,
        resp_model=GetRecordResponse,
    ),
    DataAction.list_records: _ActionSpec(
        build=lambda req: q_list_records(req.owner_id, req.status, req.limit),
        row_model=RecordRow,
        resp_model=ListRecordsResponse,
    ),
    DataAction.list_records_dated: _ActionSpec(
        build=lambda req: q_list_records_by_date(
            req.owner_id,
            start_date=req.start_date,
            end_date=req.end_date,
            limit=req.limit,
        ),
        row_model=RecordRow,
        resp_model=ListRecordsDatedResponse,
    ),
    DataAction.get_summary: _ActionSpec(
        build=lambda req: q_get_summary(req.owner_id),
        row_model=SummaryRow,
        resp_model=GetSummaryResponse,
    ),
}


@observe(name="db.run_data_tool")
def run_data_tool(req: DataToolRequest) -> DataToolResponse:
    """
    Execute a data tool request and return a typed response.

    Called by MCP server tool functions. The response is serialized to
    JSON via model_dump(mode="json") and returned as the tool result.
    """
    policy = ACTION_POLICIES.get(req.action)
    spec = _ACTION_SPECS.get(req.action)

    if not policy or not spec:
        raise ValueError(f"Unsupported action: {req.action}")

    sql, params = spec.build(req)
    rows, truncated = run_select(
        sql,
        params,
        timeout_ms=policy.statement_timeout_ms,
        max_rows=policy.max_rows,
    )

    typed_rows = [spec.row_model.model_validate(r) for r in (rows or [])]

    return spec.resp_model(
        owner_id=req.owner_id,
        rows=typed_rows,
        row_count=len(typed_rows),
        truncated=bool(truncated),
        meta={
            "timeout_ms": policy.statement_timeout_ms,
            "max_rows": policy.max_rows,
        },
    )
