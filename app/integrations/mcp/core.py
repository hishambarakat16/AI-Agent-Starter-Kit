from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from mcp import types

from .models import MCPCallResult, MCPServerConfig, MCPToolRef
from .mcp_helper import MCPHelper


def load_mcp_servers() -> list[MCPServerConfig]:
    """
    Return the list of MCP servers the agent should connect to.

    Each server exposes a set of tools. The agent sees ALL tools from ALL
    servers — tool names are namespaced as "server.tool_name" internally
    to avoid collisions, then sanitized to safe LangChain tool names.

    Add or remove servers here to change what tools are available to the agent.
    URLs are read from environment variables with sensible local defaults.
    """
    data_url   = os.getenv("MCP_DATA_URL",   "http://127.0.0.1:8051/mcp").strip()
    vector_url = os.getenv("MCP_VECTOR_URL", "http://127.0.0.1:8052/mcp").strip()
    return [
        MCPServerConfig(name="data",   url=data_url),
        MCPServerConfig(name="vector", url=vector_url),
    ]


class MCPServerClient:
    """
    HTTP client for a single MCP server.

    Wraps the MCP protocol (list_tools / call_tool) behind a clean async
    interface. Passes Langfuse trace headers on every request so tool-level
    spans appear nested under the agent's trace in Langfuse.
    """
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
    """
    Aggregates multiple MCP servers into a single interface.

    The agent only interacts with this class — it doesn't know or care which
    server a tool lives on. Resolution happens here via fq_name (server.tool).
    """
    def __init__(self, servers: list[MCPServerConfig]):
        self._servers = servers
        self._clients = {s.name: MCPServerClient(url=s.url) for s in servers}

    async def list_tools(self) -> List[MCPToolRef]:
        """List all tools across all servers, tagged with their server name."""
        out: list[MCPToolRef] = []
        for s in self._servers:
            tools = await self._clients[s.name].list_tools()
            out.extend([MCPToolRef(server=s.name, tool=t) for t in tools])
        return out

    async def call_tool(self, *, tool_name: str, arguments: Dict[str, Any]) -> MCPCallResult:
        """
        Call a tool by name. Resolves ambiguity using fq_name (server.tool).
        Raises ValueError if tool is unknown or ambiguous across servers.
        """
        tool_refs = await self.list_tools()
        fq_name = MCPHelper.resolve_fq_name(tool_refs, tool_name)
        server, raw_name = MCPHelper.split_fq_name(fq_name)
        client = self._clients.get(server)
        if client is None:
            raise ValueError(f"Unknown MCP server '{server}'")
        return await client.call_tool(raw_name, arguments)
