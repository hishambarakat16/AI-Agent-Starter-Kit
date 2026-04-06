"""
SQL Schemas — Pydantic request and response models for your MCP data tools.

Pattern overview:
  - One Request model per tool action (discriminated by action: Literal[...])
  - One Row model per table/query result shape
  - One Response model per action (wraps rows + metadata)
  - SQLToolRequest = Union of all request types (discriminated union)
    so the service layer can dispatch in one place

Why Pydantic here?
  - Validates that the MCP tool received correct arguments
  - Ensures DB rows are typed before the agent reads them
  - model_dump(mode="json") handles datetime, Decimal, UUID serialization
    automatically — no manual JSON encoding needed

Replace the example models below with models that match your schema.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Annotated, Any, Dict, List, Literal, Optional, Union
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

Number = Union[int, float, Decimal]
DT = Union[datetime, str]


# ─── Actions ──────────────────────────────────────────────────────────────────
# One enum value per tool action. Used as the discriminator field so the
# service layer can dispatch to the right query without if/elif chains.

class DataAction(str, Enum):
    get_record         = "get_record"
    list_records       = "list_records"
    list_records_dated = "list_records_dated"
    get_summary        = "get_summary"


# ─── Request models ───────────────────────────────────────────────────────────
# Each request carries `action` as a Literal so Pydantic can discriminate
# the union automatically.

class GetRecordRequest(BaseModel):
    action: Literal[DataAction.get_record]
    owner_id: str
    record_id: str


class ListRecordsRequest(BaseModel):
    action: Literal[DataAction.list_records]
    owner_id: str
    status: Optional[str] = None
    limit: Annotated[int, Field(ge=1, le=200)] = 20


class ListRecordsDatedRequest(BaseModel):
    action: Literal[DataAction.list_records_dated]
    owner_id: str
    start_date: Optional[str] = None   # ISO date string, e.g. "2024-01-01"
    end_date: Optional[str] = None
    limit: Annotated[int, Field(ge=1, le=200)] = 20


class GetSummaryRequest(BaseModel):
    action: Literal[DataAction.get_summary]
    owner_id: str


# Discriminated union — pass any of the above to the service layer
DataToolRequest = Annotated[
    Union[
        GetRecordRequest,
        ListRecordsRequest,
        ListRecordsDatedRequest,
        GetSummaryRequest,
    ],
    Field(discriminator="action"),
]


# ─── Row models ───────────────────────────────────────────────────────────────
# One Pydantic model per query result shape.
# Field types should match what your DB returns.
# Use Optional + None defaults for columns that may be NULL.

class RecordRow(BaseModel):
    id: str
    owner_id: str
    name: Optional[str] = None
    status: Optional[str] = None
    amount: Optional[Number] = None
    created_at: Optional[DT] = None

    @field_validator("id", "owner_id", mode="before")
    @classmethod
    def _to_str(cls, v: Any) -> str:
        return str(v) if v is not None else ""


class SummaryRow(BaseModel):
    owner_id: str
    owner_name: Optional[str] = None
    total_records: Optional[int] = None
    total_amount: Optional[Number] = None
    last_activity_at: Optional[DT] = None

    @field_validator("owner_id", mode="before")
    @classmethod
    def _to_str(cls, v: Any) -> str:
        return str(v) if v is not None else ""


# ─── Response models ──────────────────────────────────────────────────────────
# Every response carries row_count and truncated so the agent knows
# whether to tell the user "showing first N results, ask for more".

class BaseDataResponse(BaseModel):
    owner_id: str
    row_count: int = 0
    truncated: bool = False
    meta: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("owner_id", mode="before")
    @classmethod
    def _to_str(cls, v: Any) -> str:
        return str(v) if v is not None else ""


class GetRecordResponse(BaseDataResponse):
    action: Literal[DataAction.get_record] = DataAction.get_record
    rows: List[RecordRow] = Field(default_factory=list)


class ListRecordsResponse(BaseDataResponse):
    action: Literal[DataAction.list_records] = DataAction.list_records
    rows: List[RecordRow] = Field(default_factory=list)


class ListRecordsDatedResponse(BaseDataResponse):
    action: Literal[DataAction.list_records_dated] = DataAction.list_records_dated
    rows: List[RecordRow] = Field(default_factory=list)


class GetSummaryResponse(BaseDataResponse):
    action: Literal[DataAction.get_summary] = DataAction.get_summary
    rows: List[SummaryRow] = Field(default_factory=list)


DataToolResponse = Annotated[
    Union[
        GetRecordResponse,
        ListRecordsResponse,
        ListRecordsDatedResponse,
        GetSummaryResponse,
    ],
    Field(discriminator="action"),
]
