# langfuse_utils.py
from __future__ import annotations

from typing import Dict, Optional

from dotenv import load_dotenv
from langfuse import get_client

load_dotenv()


def lf_client():
    # Uses LANGFUSE_HOST, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY from env
    return get_client()


def current_trace_headers() -> Dict[str, str]:
    """
    Call inside an active observation/span.
    Returns headers carrying (trace_id, parent_span_id).
    """
    langfuse = lf_client()
    trace_id = langfuse.get_current_trace_id()
    parent_span_id = langfuse.get_current_observation_id()

    headers: Dict[str, str] = {}
    if trace_id:
        headers["x-langfuse-trace-id"] = str(trace_id)
    if parent_span_id:
        headers["x-langfuse-parent-span-id"] = str(parent_span_id)
    return headers


def extract_trace_context(headers: Dict[str, str]) -> Optional[Dict[str, str]]:
    """
    Convert incoming headers into Langfuse trace_context.
    """
    trace_id = headers.get("x-langfuse-trace-id")
    parent_span_id = headers.get("x-langfuse-parent-span-id")

    if not trace_id:
        return None

    ctx: Dict[str, str] = {"trace_id": trace_id}
    if parent_span_id:
        ctx["parent_span_id"] = parent_span_id
    return ctx
