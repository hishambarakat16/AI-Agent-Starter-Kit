from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from .schemas import SQLAction


@dataclass(frozen=True)
class ActionPolicy:
    max_rows: int
    statement_timeout_ms: int


ACTION_POLICIES: Dict[SQLAction, ActionPolicy] = {
    SQLAction.get_customer_profile: ActionPolicy(max_rows=1, statement_timeout_ms=1500),
    SQLAction.list_accounts: ActionPolicy(max_rows=50, statement_timeout_ms=1500),
    SQLAction.get_account_summary: ActionPolicy(max_rows=50, statement_timeout_ms=2000),
    SQLAction.list_transactions: ActionPolicy(max_rows=200, statement_timeout_ms=2500),
}
