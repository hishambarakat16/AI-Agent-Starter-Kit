from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from mcp import types

from .models import MCPCallResult, MCPServerConfig, MCPToolRef
from .mcp_helper import MCPHelper


def load_mcp_servers() -> list[MCPServerConfig]:
    """Load all MCP servers (for backward compatibility)."""
    return load_chat_mcp_servers() + load_incident_mcp_servers()


def load_chat_mcp_servers() -> list[MCPServerConfig]:
    """Load MCP servers for chat agent (SQL and Policy only)."""
    sql_url = os.getenv("MCP_SQL_URL", "http://127.0.0.1:8051/mcp").strip()
    policy_url = os.getenv("MCP_POLICY_URL", "http://127.0.0.1:8052/mcp").strip()
    return [
        MCPServerConfig(name="sql", url=sql_url),
        MCPServerConfig(name="policy", url=policy_url),
    ]


def load_incident_mcp_servers() -> list[MCPServerConfig]:
    """Load MCP servers for incident analysis (Card Events, Rules Engine, and Auth/OTP)."""
    card_events_url = os.getenv("MCP_CARD_EVENTS_URL", "http://127.0.0.1:8053/mcp").strip()
    rules_engine_url = os.getenv("MCP_RULES_ENGINE_URL", "http://127.0.0.1:8054/mcp").strip()
    auth_url = os.getenv("MCP_AUTH_URL", "http://127.0.0.1:8055/mcp").strip()
    return [
        MCPServerConfig(name="card_events", url=card_events_url),
        MCPServerConfig(name="rules_engine", url=rules_engine_url),
        MCPServerConfig(name="auth_otp", url=auth_url),
    ]


class MCPServerClient:
    def __init__(self, *, url: str, auth_token: Optional[str] = None):
        self._url = url
        self._auth_token = auth_token

    def _headers(self) -> Optional[Dict[str, str]]:
        if not self._auth_token:
            return None
        return {"Authorization": f"Bearer {self._auth_token}"}

    async def list_tools(self) -> List[types.Tool]:
        async def _run(session):
            resp = await session.list_tools()
            return list(resp.tools)

        return await MCPHelper.with_session(self._url, _run, headers=self._headers())

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> MCPCallResult:
        async def _run(session):
            result = await session.call_tool(name, arguments=arguments)
            return MCPHelper.parse_call_result(result)

        return await MCPHelper.with_session(self._url, _run, headers=self._headers())


class MCPMultiClient:
    def __init__(self, servers: list[MCPServerConfig]):
        self._servers = servers
        self._clients = {s.name: MCPServerClient(url=s.url) for s in servers}

    async def list_tools(self) -> List[MCPToolRef]:
        out: list[MCPToolRef] = []
        for s in self._servers:
            tools = await self._clients[s.name].list_tools()
            out.extend([MCPToolRef(server=s.name, tool=t) for t in tools])
        return out

    async def call_tool(self, *, tool_name: str, arguments: Dict[str, Any]) -> MCPCallResult:
        tool_refs = await self.list_tools()
        fq_name = MCPHelper.resolve_fq_name(tool_refs, tool_name)

        server, raw_name = MCPHelper.split_fq_name(fq_name)
        client = self._clients.get(server)
        if client is None:
            raise ValueError(f"Unknown MCP server '{server}'")

        return await client.call_tool(raw_name, arguments)
