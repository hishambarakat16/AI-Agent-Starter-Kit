# app/sql/schemas.py
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Annotated, Any, Dict, List, Literal, Optional, Union
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

Number = Union[int, float, Decimal]
DT = Union[datetime, str]


class SQLAction(str, Enum):
    get_customer_profile = "get_customer_profile"
    list_accounts = "list_accounts"
    get_account_summary = "get_account_summary"
    list_transactions = "list_transactions"


# =========================
# Request models
# =========================

class BaseRequest(BaseModel):
    customer_id: UUID


class GetCustomerProfileRequest(BaseRequest):
    action: Literal[SQLAction.get_customer_profile]


class ListAccountsRequest(BaseRequest):
    action: Literal[SQLAction.list_accounts]


class GetAccountSummaryRequest(BaseRequest):
    action: Literal[SQLAction.get_account_summary]
    account_id: Optional[UUID] = None


class ListTransactionsRequest(BaseRequest):
    action: Literal[SQLAction.list_transactions]
    account_id: Optional[UUID] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    limit: Annotated[int, Field(ge=1, le=200)] = 50


SQLToolRequest = Annotated[
    Union[
        GetCustomerProfileRequest,
        ListAccountsRequest,
        GetAccountSummaryRequest,
        ListTransactionsRequest,
    ],
    Field(discriminator="action"),
]


# =========================
# Row models
# =========================

class CustomerProfileRow(BaseModel):
    customer_id: str
    full_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    created_at: Optional[DT] = None
    updated_at: Optional[DT] = None

    @field_validator("customer_id", mode="before")
    @classmethod
    def _coerce_customer_id(cls, v: Any) -> str:
        return str(v) if v is not None else ""
    
    
class AccountRow(BaseModel):
    account_id: str
    account_type: Optional[str] = None
    currency: Optional[str] = None
    credit_limit: Optional[Number] = None
    is_active: Optional[bool] = None
    opened_at: Optional[DT] = None
    closed_at: Optional[DT] = None
    @field_validator("account_id", mode="before")
    @classmethod
    def _coerce_account_id(cls, v: Any) -> str:
        return str(v) if v is not None else ""

class AccountSummaryRow(BaseModel):
    account_id: str
    account_type: Optional[str] = None
    currency: Optional[str] = None
    credit_limit: Optional[Number] = None
    is_active: Optional[bool] = None
    opened_at: Optional[DT] = None
    closed_at: Optional[DT] = None

    tx_count: Optional[int] = None
    total_in: Optional[Number] = None
    total_out: Optional[Number] = None
    last_tx_at: Optional[DT] = None


class TransactionRow(BaseModel):
    tx_id: str
    account_id: str
    tx_type: Optional[str] = None
    amount: Optional[Number] = None
    currency: Optional[str] = None
    description: Optional[str] = None
    occurred_at: Optional[DT] = None
    created_at: Optional[DT] = None


# =========================
# Typed response models
# =========================

class BaseSQLResponse(BaseModel):
    customer_id: str
    row_count: int = 0
    truncated: bool = False
    meta: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("customer_id", mode="before")
    @classmethod
    def _coerce_customer_id(cls, v: Any) -> str:
        return str(v) if v is not None else ""


class GetCustomerProfileResponse(BaseSQLResponse):
    action: Literal[SQLAction.get_customer_profile] = SQLAction.get_customer_profile
    rows: List[CustomerProfileRow] = Field(default_factory=list)


class ListAccountsResponse(BaseSQLResponse):
    action: Literal[SQLAction.list_accounts] = SQLAction.list_accounts
    rows: List[AccountRow] = Field(default_factory=list)


class GetAccountSummaryResponse(BaseSQLResponse):
    action: Literal[SQLAction.get_account_summary] = SQLAction.get_account_summary
    rows: List[AccountSummaryRow] = Field(default_factory=list)


class ListTransactionsResponse(BaseSQLResponse):
    action: Literal[SQLAction.list_transactions] = SQLAction.list_transactions
    rows: List[TransactionRow] = Field(default_factory=list)


SQLToolTypedResponse = Annotated[
    Union[
        GetCustomerProfileResponse,
        ListAccountsResponse,
        GetAccountSummaryResponse,
        ListTransactionsResponse,
    ],
    Field(discriminator="action"),
]
