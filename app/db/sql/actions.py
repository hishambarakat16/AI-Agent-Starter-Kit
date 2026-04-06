"""
Action Policies — per-action limits for query safety.

Every action gets:
  max_rows:             Hard cap on rows returned. Prevents the agent from
                        receiving thousands of rows it can't reason about.
                        If the query would return more, truncated=True is set.

  statement_timeout_ms: PostgreSQL kills the query if it runs longer than
                        this. Prevents slow queries from blocking the agent's
                        tool call and timing out the whole request.

Tune these based on:
  - How many rows the LLM actually needs to answer a question (usually < 50)
  - How long your queries typically take (add 2-3× buffer)
  - Your overall request timeout (queries + LLM reasoning must fit within it)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from .schemas import DataAction


@dataclass(frozen=True)
class ActionPolicy:
    max_rows: int
    statement_timeout_ms: int


ACTION_POLICIES: Dict[DataAction, ActionPolicy] = {
    # Single-record lookups — very tight limits
    DataAction.get_record: ActionPolicy(
        max_rows=1,
        statement_timeout_ms=1_500,
    ),
    # List queries — moderate limit, fast timeout
    DataAction.list_records: ActionPolicy(
        max_rows=50,
        statement_timeout_ms=2_000,
    ),
    # Date-range queries — slightly more rows allowed, bit more time
    DataAction.list_records_dated: ActionPolicy(
        max_rows=100,
        statement_timeout_ms=2_500,
    ),
    # Aggregation — single row back, but query may be heavier
    DataAction.get_summary: ActionPolicy(
        max_rows=10,
        statement_timeout_ms=3_000,
    ),
}
