# app/sql/sql_service.py
from __future__ import annotations

from typing import Any, Callable, Dict, Tuple, Type
from typing import NamedTuple

from fastapi import HTTPException, status
from langfuse import observe

from .allowed_actions import ACTION_POLICIES
from .schemas import (SQLAction, SQLToolRequest,SQLToolTypedResponse,
    CustomerProfileRow,
    AccountRow,
    AccountSummaryRow,
    TransactionRow,
    GetCustomerProfileResponse,
    ListAccountsResponse,
    GetAccountSummaryResponse,
    ListTransactionsResponse,
)
from .sql_guard import validate_request
from .sql_queries import (
    q_get_account_summary,
    q_get_customer_profile,
    q_list_accounts,
    q_list_transactions,
)
from .sql_utils import run_select


class _ActionSpec(NamedTuple):
    # Using Any here avoids typing pain from SQLToolRequest being an Annotated Union.
    build: Callable[[Any], Tuple[str, Dict[str, Any]]]
    row_model: Type
    resp_model: Type


_ACTION_SPECS: Dict[SQLAction, _ActionSpec] = {
    SQLAction.get_customer_profile: _ActionSpec(
        build=lambda req: q_get_customer_profile(req.customer_id),
        row_model=CustomerProfileRow,
        resp_model=GetCustomerProfileResponse,
    ),
    SQLAction.list_accounts: _ActionSpec(
        build=lambda req: q_list_accounts(req.customer_id),
        row_model=AccountRow,
        resp_model=ListAccountsResponse,
    ),
    SQLAction.get_account_summary: _ActionSpec(
        build=lambda req: q_get_account_summary(req.customer_id, getattr(req, "account_id", None)),
        row_model=AccountSummaryRow,
        resp_model=GetAccountSummaryResponse,
    ),
    SQLAction.list_transactions: _ActionSpec(
        build=lambda req: q_list_transactions(
            req.customer_id,
            account_id=getattr(req, "account_id", None),
            start_date=getattr(req, "start_date", None),
            end_date=getattr(req, "end_date", None),
            limit=getattr(req, "limit", 50),
        ),
        row_model=TransactionRow,
        resp_model=ListTransactionsResponse,
    ),
}

@observe(name="sql.run_sql_tool")
def run_sql_tool(req: SQLToolRequest) -> SQLToolTypedResponse:
    validate_request(req)

    policy = ACTION_POLICIES.get(req.action)
    spec = _ACTION_SPECS.get(req.action)
    if not policy or not spec:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported action: {req.action}",
        )

    sql, params = spec.build(req)
    rows, truncated = run_select(
        sql,
        params,
        timeout_ms=policy.statement_timeout_ms,
        max_rows=policy.max_rows,
    )

    row_model = spec.row_model
    resp_model = spec.resp_model

    typed_rows = [row_model.model_validate(r) for r in (rows or [])]

    base_kwargs = dict(
        rows=typed_rows,
        row_count=len(typed_rows),
        truncated=bool(truncated),
        meta={"timeout_ms": policy.statement_timeout_ms, "max_rows": policy.max_rows},
    )

    return resp_model(customer_id=req.customer_id, **base_kwargs)
