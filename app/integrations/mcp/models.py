from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from mcp import types


@dataclass(frozen=True)
class MCPServerConfig:
    name: str
    url: str


@dataclass(frozen=True)
class MCPCallResult:
    text: str
    structured: Optional[dict] = None


@dataclass(frozen=True)
class MCPToolRef:
    server: str
    tool: types.Tool

    @property
    def name(self) -> str:
        return self.tool.name

    @property
    def description(self) -> str:
        return self.tool.description or ""

    @property
    def input_schema(self) -> dict:
        return getattr(self.tool, "inputSchema", None) or {}

    @property
    def fq_name(self) -> str:
        return f"{self.server}.{self.tool.name}"
