# app/sql/sql_utils.py
from __future__ import annotations

from typing import Any, Dict, List, Tuple
from uuid import UUID
from langfuse import observe

from app.utils.connect_db import get_conn


def _adapt_value(v: Any) -> Any:
    if isinstance(v, UUID):
        return str(v)
    if isinstance(v, list):
        return [_adapt_value(x) for x in v]
    if isinstance(v, tuple):
        return tuple(_adapt_value(x) for x in v)
    if isinstance(v, dict):
        return {k: _adapt_value(val) for k, val in v.items()}
    return v


def _adapt_params(params: Dict[str, Any]) -> Dict[str, Any]:
    return {k: _adapt_value(v) for k, v in params.items()}


def _mask_email(email: str) -> str:
    s = (email or "").strip()
    if "@" not in s:
        return s
    local, domain = s.split("@", 1)
    if not local:
        return f"*@{domain}"
    if len(local) <= 2:
        masked_local = local[0] + "*"
    else:
        masked_local = local[0] + ("*" * (len(local) - 2)) + local[-1]
    return f"{masked_local}@{domain}"


def _mask_phone(phone: str) -> str:
    s = "".join(ch for ch in (phone or "") if ch.isdigit())
    if not s:
        return phone
    if len(s) <= 4:
        return "*" * len(s)
    return ("*" * (len(s) - 4)) + s[-4:]


def _mask_uuid(u: str) -> str:
    s = (u or "").strip()
    if len(s) < 8:
        return s
    # show first 4 and last 4
    return f"{s[:4]}…{s[-4:]}"


def _sanitize_value(key: str, v: Any) -> Any:
    if v is None:
        return None

    k = (key or "").lower()

    # Emails
    if "email" in k and isinstance(v, str):
        return _mask_email(v)

    # Phones
    if ("phone" in k or "mobile" in k) and isinstance(v, str):
        return _mask_phone(v)

    # IDs (UUID-ish)
    if k.endswith("_id") or k in {"id", "customer_id", "account_id", "tx_id", "user_id"}:
        if isinstance(v, UUID):
            return _mask_uuid(str(v))
        if isinstance(v, str):
            return _mask_uuid(v)

    return v


def sanitize_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in rows or []:
        out.append({k: _sanitize_value(k, v) for k, v in r.items()})
    return out


@observe(name="sql.run_select")
def run_select(
    sql: str,
    params: Dict[str, Any],
    *,
    timeout_ms: int,
    max_rows: int,
) -> Tuple[List[Dict[str, Any]], bool]:
    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SET LOCAL statement_timeout = %s", (timeout_ms,))
                cur.execute("SET LOCAL TRANSACTION READ ONLY")

                cur.execute(sql, _adapt_params(params))

                cols = [d[0] for d in cur.description] if cur.description else []
                fetched = cur.fetchmany(max_rows + 1)

                truncated = len(fetched) > max_rows
                fetched = fetched[:max_rows]

                rows: List[Dict[str, Any]] = []
                for row in fetched:
                    rows.append({cols[i]: row[i] for i in range(len(cols))})

                return sanitize_rows(rows), truncated
    finally:
        conn.close()
