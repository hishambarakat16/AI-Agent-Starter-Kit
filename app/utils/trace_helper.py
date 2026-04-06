# app/utils/trace_helper.py
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional

from dotenv import load_dotenv
from langfuse import get_client
from mcp.server.fastmcp import Context
from opentelemetry.propagate import inject
import json

load_dotenv()

logger = logging.getLogger("trace")


class TraceHelper:
    """
    Thin Langfuse wrapper:
    - fail-open (never break app flow)
    - produces a trace_context payload suitable for cross-service linking
    - produces an MCP-friendly meta object (you can later pick this up in MCP server)
    """

    TRACE_ID_KEY = "trace_id"
    PARENT_SPAN_ID_KEY = "parent_span_id"


   
    @staticmethod
    def current_trace_headers() -> Dict[str, str]:

        h: Dict[str, Any] = {}

        if "headers" in h and isinstance(h["headers"], dict):
            h = dict(h["headers"])

        out: Dict[str, str] = {}
        for k, v in (h or {}).items():
            if v is None:
                continue
            if isinstance(v, (str, bytes)):
                out[str(k)] = v.decode() if isinstance(v, bytes) else v
            elif isinstance(v, (dict, list, tuple)):
                out[str(k)] = json.dumps(v, ensure_ascii=False)
            else:
                out[str(k)] = str(v)

        return out
    
    
    @staticmethod
    def client():
        return get_client()

    @staticmethod
    def current_trace_context() -> Optional[Dict[str, str]]:
        """
        Returns {"trace_id": "...", "parent_span_id": "..."} if available.
        None if no active trace/span.
        """
        try:
            c = TraceHelper.client()
            trace_id = c.get_current_trace_id()
            span_id = c.get_current_observation_id()
            if not trace_id:
                return None

            ctx: Dict[str, str] = {TraceHelper.TRACE_ID_KEY: str(trace_id)}
            if span_id:
                ctx[TraceHelper.PARENT_SPAN_ID_KEY] = str(span_id)
            return ctx
        except Exception:
            return None

    @staticmethod
    def mcp_meta() -> Optional[Dict[str, Any]]:
        """
        MCP-friendly meta blob. We keep it namespaced and explicit.

        Example shape:
        {
          "langfuse": {
            "trace_id": "...",
            "parent_span_id": "..."
          }
        }
        """
        ctx = TraceHelper.current_trace_context()
        if not ctx:
            return None
        return {"langfuse": ctx}

    @staticmethod
    @contextmanager
    def span(name: str, *, input: Any = None, metadata: Optional[Dict[str, Any]] = None) -> Iterator[None]:
        """
        Small context manager for spans. Use sparingly (only at boundaries).
        Never raises.
        """
        try:
            c = TraceHelper.client()
            with c.start_as_current_observation(
                as_type="span",
                name=name,
                input=input,
                metadata=metadata,
            ):
                yield
        except Exception as e:
            logger.debug("trace span failed name=%s err=%s", name, str(e))
            yield



    @staticmethod
    def trace_context_from_mcp_ctx(ctx: Optional[Context]) -> Optional[Dict[str, str]]:
        """
        Expects meta injected by client:
          meta = {"langfuse": {"trace_id": "...", "parent_span_id": "..."}}

        FastMCP exposes this via ctx.request_meta.
        """
        if ctx is None:
            return None

        meta = getattr(ctx, "request_meta", None) or {}
        lf = meta.get("langfuse") or {}

        trace_id = lf.get("trace_id")
        parent_span_id = lf.get("parent_span_id")

        if not trace_id:
            return None

        out: Dict[str, str] = {"trace_id": str(trace_id)}
        if parent_span_id:
            out["parent_span_id"] = str(parent_span_id)
        return out

    @staticmethod
    @contextmanager
    def span_from_mcp_ctx(
        ctx: Optional[Context],
        *,
        name: str,
        input: Any = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Iterator[None]:
        """
        Start a Langfuse span linked to the upstream trace (if present).
        Fail-open.
        """
        try:
            c = TraceHelper.client()
            trace_ctx = TraceHelper.trace_context_from_mcp_ctx(ctx)

            with c.start_as_current_observation(
                as_type="span",
                name=name,
                input=input,
                metadata=metadata,
                trace_context=trace_ctx,  # <-- the important join
            ):
                yield
        except Exception as e:
            logger.debug("trace span_from_mcp_ctx failed name=%s err=%s", name, str(e))
            yield