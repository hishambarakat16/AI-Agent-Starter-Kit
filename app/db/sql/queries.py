"""
SQL Query Definitions — parameterized queries for your data model.

Each function returns a (sql_string, params_dict) tuple.
The runner (runner.py) executes them safely with timeouts and row limits.

Design rules:
  - NEVER concatenate user input into SQL strings (SQL injection risk)
  - ALWAYS use %(param_name)s placeholders — psycopg2 handles escaping
  - One function per logical query — keeps queries testable in isolation
  - Return (sql, params) only — no DB connection here, that's runner.py's job
"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, Optional, Tuple


# ─── REPLACE WITH YOUR QUERIES ───────────────────────────────────────────────
# The patterns below show how to structure parameterized queries.
# Swap out the table names and columns for your schema.
# Use %(param_name)s syntax — never f-strings with user data.


def q_get_record(record_id: str) -> Tuple[str, Dict[str, Any]]:
    """Fetch a single record by its primary key."""
    sql = """
    SELECT id, name, status, created_at, updated_at
    FROM your_table
    WHERE id = %(record_id)s
    """
    return sql, {"record_id": record_id}


def q_list_records(
    owner_id: str,
    status: Optional[str] = None,
    limit: int = 20,
) -> Tuple[str, Dict[str, Any]]:
    """
    List records for an owner, with an optional status filter.

    Pattern: conditional WHERE clauses using IS NULL fallback.
    %(status)s IS NULL means "skip this filter if None was passed" —
    clean way to make filters optional without string concatenation.
    """
    sql = """
    SELECT id, owner_id, name, status, amount, created_at
    FROM your_table
    WHERE owner_id = %(owner_id)s
      AND (%(status)s IS NULL OR status = %(status)s)
    ORDER BY created_at DESC
    LIMIT %(limit)s
    """
    return sql, {"owner_id": owner_id, "status": status, "limit": limit}


def q_list_records_by_date(
    owner_id: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    limit: int = 20,
) -> Tuple[str, Dict[str, Any]]:
    """
    List records filtered by date range.

    Pattern: date range with IS NULL fallback on both ends so each
    bound is optional independently.
    """
    sql = """
    SELECT id, owner_id, name, amount, occurred_at
    FROM your_table
    WHERE owner_id = %(owner_id)s
      AND (%(start_date)s IS NULL OR occurred_at >= %(start_date)s)
      AND (%(end_date)s IS NULL OR occurred_at < (%(end_date)s::date + INTERVAL '1 day'))
    ORDER BY occurred_at DESC
    LIMIT %(limit)s
    """
    return sql, {
        "owner_id": owner_id,
        "start_date": start_date,
        "end_date": end_date,
        "limit": limit,
    }


def q_get_summary(owner_id: str) -> Tuple[str, Dict[str, Any]]:
    """
    Aggregation query — totals and counts for a user.

    Pattern: LEFT JOIN + COALESCE so users with no records still
    get a row back (with 0s instead of NULL).
    """
    sql = """
    SELECT
        u.id                                              AS owner_id,
        u.name                                            AS owner_name,
        COUNT(r.id)                                       AS total_records,
        COALESCE(SUM(r.amount), 0)                        AS total_amount,
        COALESCE(MAX(r.occurred_at), NULL)                AS last_activity_at
    FROM users u
    LEFT JOIN your_table r ON r.owner_id = u.id
    WHERE u.id = %(owner_id)s
    GROUP BY u.id, u.name
    """
    return sql, {"owner_id": owner_id}
