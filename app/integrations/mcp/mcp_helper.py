from __future__ import annotations

import re
import json
import httpx
from uuid import UUID
from datetime import date

from mcp import ClientSession, types
from mcp.client.streamable_http import streamable_http_client
from pydantic import BaseModel, Field, create_model

from typing import Any, Dict, List, Optional, Tuple, Type

from .models import MCPCallResult, MCPToolRef
from .langfuse_utils import current_trace_headers
import logging

class MCPHelper:
    
    @staticmethod
    async def with_session(url: str, fn, headers: Optional[Dict[str, str]] = None):
        trace_headers = current_trace_headers()
        if not trace_headers:
            logging.info("WARN mcp trace headers empty (no active langfuse span?)")
        else:
            print(f"INFO mcp trace headers ok trace_id={trace_headers.get('x-langfuse-trace-id')} "
                f"parent={trace_headers.get('x-langfuse-parent-span-id')}")
            
        merged: Dict[str, str] = {}
        merged.update(trace_headers)
        if headers:
            merged.update(headers)

        http_client = httpx.AsyncClient(headers=merged, timeout=httpx.Timeout(10.0))
        try:
            async with streamable_http_client(url, http_client=http_client) as (read, write, _get_session_id):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    return await fn(session)
        finally:
            await http_client.aclose()

    @staticmethod
    def parse_call_result(result: Any) -> MCPCallResult:
        structured = None
        if getattr(result, "structuredContent", None):
            structured = dict(result.structuredContent)

        text_blocks: list[str] = []
        for block in getattr(result, "content", []) or []:
            if isinstance(block, types.TextContent):
                text_blocks.append(block.text)
            else:
                text_blocks.append(str(block))

        # Handle multiple text blocks (list responses)
        if len(text_blocks) > 1:
            logging.info("MCP response has %d text blocks. Block lengths: %s",
                        len(text_blocks), [len(b) for b in text_blocks])
            # Multiple blocks usually means a list response where each block is a JSON object
            # Wrap them in array brackets to create valid JSON array
            text = "[" + ",".join(t.strip() for t in text_blocks if (t or "").strip()) + "]"
        elif len(text_blocks) == 1:
            text = text_blocks[0].strip()
        else:
            text = ""

        if not text and structured is not None:
            text = json.dumps(structured, ensure_ascii=False)

        return MCPCallResult(text=text, structured=structured)

    @staticmethod
    def resolve_fq_name(tool_refs: List[MCPToolRef], tool_name: str) -> str:
        if "." in tool_name:
            return tool_name

        matches = [t for t in tool_refs if t.name == tool_name]
        if not matches:
            raise ValueError(f"Unknown MCP tool '{tool_name}'")
        if len(matches) > 1:
            servers = ", ".join(sorted({t.server for t in matches}))
            raise ValueError(f"Ambiguous MCP tool '{tool_name}' across servers: {servers}")
        return matches[0].fq_name

    @staticmethod
    def split_fq_name(fq_name: str) -> Tuple[str, str]:
        server, raw_name = fq_name.split(".", 1)
        return server, raw_name

    @staticmethod
    def sanitize_tool_name(name: str) -> str:
        _VALID = re.compile(r"^[a-zA-Z0-9_-]+$")
        
        if _VALID.match(name):
            return name
        safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", name).strip("_")
        if not safe:
            safe = "tool"
        return safe

    @staticmethod
    def ensure_unique(name: str, used: set[str]) -> str:
        if name not in used:
            used.add(name)
            return name
        i = 2
        while f"{name}_{i}" in used:
            i += 1
        final = f"{name}_{i}"
        used.add(final)
        return final

    @staticmethod
    def _schema_type_to_py(prop_schema: Dict[str, Any]) -> Any:
        t = prop_schema.get("type", "string")
        fmt = prop_schema.get("format")

        if t == "string" and fmt == "uuid":
            return UUID
        if t == "string" and fmt == "date":
            return date
        if t == "string":
            return str
        if t == "integer":
            return int
        if t == "number":
            return float
        if t == "boolean":
            return bool
        if t == "array":
            return list
        if t == "object":
            return dict
        return Any

    @staticmethod
    def _json_schema_to_pydantic(schema: Dict[str, Any], model_name: str) -> Type[BaseModel]:
        if not schema or schema.get("type") != "object":
            return create_model(model_name, input=(dict[str, Any], Field(...)))

        props: Dict[str, Any] = schema.get("properties", {}) or {}
        required = set(schema.get("required", []) or {})

        fields: Dict[str, Tuple[Any, Any]] = {}
        for name, prop_schema in props.items():
            py_type = MCPHelper._schema_type_to_py(prop_schema)
            desc = prop_schema.get("description")

            if name in required:
                fields[name] = (py_type, Field(..., description=desc))
            else:
                fields[name] = (Optional[py_type], Field(default=None, description=desc))

        return create_model(model_name, **fields)  # type: ignore[arg-type]
