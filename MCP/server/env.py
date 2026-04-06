from __future__ import annotations

import os


def get_host() -> str:
    return os.getenv("MCP_HOST", "127.0.0.1")


def get_port(default: int) -> int:
    raw = os.getenv("MCP_PORT")
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default
