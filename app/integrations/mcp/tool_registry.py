from __future__ import annotations
from typing import Any, List

from langchain_core.tools import StructuredTool

from .core import MCPMultiClient
from .models import MCPToolRef
from .mcp_helper import MCPHelper


class MCPToolRegistry:
    """
    Converts ALL MCP tools (across servers) into LangChain StructuredTools
    with namespaced names.
    """

    def __init__(self, client: MCPMultiClient):
        self._client = client

    async def get_tools(self) -> List[StructuredTool]:
        tool_refs: list[MCPToolRef] = await self._client.list_tools()
        lc_tools: list[StructuredTool] = []
        used_names: set[str] = set()

        for ref in tool_refs:
            fq_name = ref.fq_name
            t = ref.tool
            safe_name = MCPHelper.ensure_unique(MCPHelper.sanitize_tool_name(fq_name), used_names)

            input_schema = getattr(t, "inputSchema", None) or {}
            args_model = MCPHelper._json_schema_to_pydantic(input_schema, model_name=f"{fq_name.replace('.', '_')}_Args")

            async def _acall(_fq_name: str, **kwargs: Any) -> str:
                res = await self._client.call_tool(tool_name=_fq_name, arguments=kwargs)
                return res.text

            async def acall(_fq_name: str = fq_name, **kwargs: Any) -> str:
                return await _acall(_fq_name, **kwargs)

            lc_tools.append(
                StructuredTool.from_function(
                    coroutine=acall,
                    name=safe_name,
                    description=t.description or "",
                    args_schema=args_model,
                )
            )

        return lc_tools
