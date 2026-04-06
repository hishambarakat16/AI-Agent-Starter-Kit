# mcp_trace_context.py
from __future__ import annotations

from contextvars import ContextVar
from typing import Dict, Optional

_TRACE_CONTEXT: ContextVar[Optional[Dict[str, str]]] = ContextVar("lf_trace_context", default=None)

def set_trace_context(ctx: Optional[Dict[str, str]]) -> None:
    _TRACE_CONTEXT.set(ctx)

def get_trace_context() -> Optional[Dict[str, str]]:
    return _TRACE_CONTEXT.get()
