from __future__ import annotations

from typing import Dict, Optional

from .mcp_trace_context import set_trace_context  # ContextVar helper


def _headers_from_scope(scope: dict) -> Dict[str, str]:
    raw = scope.get("headers") or []
    out: Dict[str, str] = {}
    for k, v in raw:
        try:
            out[k.decode("utf-8").lower()] = v.decode("utf-8")
        except Exception:
            continue
    return out


def _extract_trace_context(headers: Dict[str, str]) -> Optional[Dict[str, str]]:
    trace_id = headers.get("x-langfuse-trace-id")
    parent_span_id = headers.get("x-langfuse-parent-span-id")
    if not trace_id:
        return None

    ctx: Dict[str, str] = {"trace_id": str(trace_id)}
    if parent_span_id:
        ctx["parent_span_id"] = str(parent_span_id)
    return ctx


class LangfuseMCPTraceJoinMiddleware:
    """
    Extract trace context from headers and store it for the request lifetime.
    Does NOT create a span.
    Tool functions will explicitly join via trace_context=get_trace_context().
    """
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return await self.app(scope, receive, send)

        headers = _headers_from_scope(scope)
        trace_context = _extract_trace_context(headers)

        set_trace_context(trace_context)

        return await self.app(scope, receive, send)
