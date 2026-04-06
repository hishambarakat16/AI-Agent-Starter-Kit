from __future__ import annotations

from datetime import date
from typing import Any, Dict, Optional, Tuple
from uuid import UUID



def q_get_customer_profile(customer_id: UUID) -> Tuple[str, Dict[str, Any]]:
    sql = """
    SELECT customer_id, full_name, email, phone, created_at, updated_at
    FROM core.customers
    WHERE customer_id = %(customer_id)s
    """
    return sql, {"customer_id": customer_id}


def q_list_accounts(customer_id: UUID) -> Tuple[str, Dict[str, Any]]:
    sql = """
    SELECT
      account_id,
      account_type,
      currency,
      credit_limit,
      is_active,
      opened_at,
      closed_at
    FROM core.accounts
    WHERE customer_id = %(customer_id)s
    ORDER BY opened_at DESC
    """
    return sql, {"customer_id": customer_id}


def q_get_account_summary(customer_id: UUID, account_id: Optional[UUID]) -> Tuple[str, Dict[str, Any]]:
    # Summary per account (or single account if account_id provided)
    sql = """
    SELECT
      a.account_id,
      a.account_type,
      a.currency,
      a.credit_limit,
      a.is_active,
      a.opened_at,
      a.closed_at,
      COUNT(t.tx_id) AS tx_count,
      COALESCE(SUM(CASE WHEN t.tx_type IN ('deposit', 'refund') THEN t.amount ELSE 0 END), 0) AS total_in,
      COALESCE(SUM(CASE WHEN t.tx_type IN ('purchase', 'transfer') THEN t.amount ELSE 0 END), 0) AS total_out,
      COALESCE(MAX(t.occurred_at), NULL) AS last_tx_at
    FROM core.accounts a
    LEFT JOIN core.transactions t ON t.account_id = a.account_id
    WHERE a.customer_id = %(customer_id)s
      AND (%(account_id)s IS NULL OR a.account_id = %(account_id)s)
    GROUP BY a.account_id
    ORDER BY a.opened_at DESC
    """
    return sql, {"customer_id": customer_id, "account_id": account_id}


def q_list_transactions(
    customer_id: UUID,
    *,
    account_id: Optional[UUID],
    start_date: Optional[date],
    end_date: Optional[date],
    limit: int,
) -> Tuple[str, Dict[str, Any]]:
    sql = """
    SELECT
      t.tx_id,
      t.account_id,
      t.tx_type,
      t.amount,
      t.currency,
      t.description,
      t.occurred_at,
      t.created_at
    FROM core.transactions t
    JOIN core.accounts a ON a.account_id = t.account_id
    WHERE a.customer_id = %(customer_id)s
      AND (%(account_id)s IS NULL OR t.account_id = %(account_id)s)
      AND (%(start_date)s IS NULL OR t.occurred_at >= %(start_date)s)
      AND (%(end_date)s IS NULL OR t.occurred_at < (%(end_date)s::date + INTERVAL '1 day'))
    ORDER BY t.occurred_at DESC
    LIMIT %(limit)s
    """
    return sql, {
        "customer_id": customer_id,
        "account_id": account_id,
        "start_date": start_date,
        "end_date": end_date,
        "limit": limit,
    }
