# app/MCP/error_handling.py
from __future__ import annotations

import os
import traceback
from typing import Any, Callable, TypeVar


T = TypeVar("T")


def _debug_enabled() -> bool:
    """
    Enable verbose tool error output when running locally/dev.
    Set: MCP_TOOL_DEBUG_ERRORS=1
    """
    return os.getenv("MCP_TOOL_DEBUG_ERRORS", "").strip().lower() in {"1", "true", "yes", "on"}


def tool_ok(payload: dict) -> dict:
    # Standard success envelope (optional, but makes debugging consistent).
    return {"ok": True, **payload}


def tool_error(tool_name: str, exc: Exception, *, input_echo: dict[str, Any] | None = None) -> dict:
    """
    Standard error envelope for MCP tools.
    - Does NOT raise: returns structured error payload.
    - Includes traceback only if MCP_TOOL_DEBUG_ERRORS is enabled.
    """
    out: dict[str, Any] = {
        "ok": False,
        "tool": tool_name,
        "error_type": type(exc).__name__,
        "error_message": str(exc),
    }
    if input_echo is not None:
        out["input_echo"] = input_echo

    if _debug_enabled():
        out["traceback"] = traceback.format_exc()

    return out


def run_tool(tool_name: str, fn: Callable[[], dict], *, input_echo: dict[str, Any] | None = None) -> dict:
    """
    Wrap tool body to ensure exceptions return structured errors.
    """
    try:
        return tool_ok(fn())
    except Exception as e:
        return tool_error(tool_name, e, input_echo=input_echo)


def norm_bool(value: Any, default: bool) -> bool:
    return default if value is None else bool(value)


def norm_int(value: Any, default: int) -> int:
    if value is None:
        return int(default)
    return int(value)


def norm_float(value: Any, default: float) -> float:
    if value is None:
        return float(default)
    return float(value)


def norm_str(value: Any, default: str) -> str:
    if value is None:
        return str(default)
    return str(value)
