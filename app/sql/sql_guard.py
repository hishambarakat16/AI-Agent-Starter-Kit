from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import HTTPException, status

from .schemas import SQLToolRequest


def _ensure_date_order(start: Optional[date], end: Optional[date]) -> None:
    if start and end and start > end:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start_date must be <= end_date",
        )


def validate_request(req: SQLToolRequest) -> None:
    # keep it simple: only sanity checks here
    if hasattr(req, "start_date") or hasattr(req, "end_date"):
        _ensure_date_order(getattr(req, "start_date", None), getattr(req, "end_date", None))
