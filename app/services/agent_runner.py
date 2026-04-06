# app/services/agent_runner.py
from __future__ import annotations

import logging
import time
from typing import AsyncIterator, Optional, Sequence, Tuple

from langchain_core.messages import AIMessage, HumanMessage

from app.graphs import build_fintech_graph
from app.integrations.mcp import MCPToolRegistry
from app.repository import ChatRepository

from langfuse.langchain import CallbackHandler
from langfuse import observe, get_client

from app.utils import AIHelper


logger = logging.getLogger("services")


class AgentRunner:
    def __init__(self, tool_registry: MCPToolRegistry, max_tool_rounds: int = 6):
        self._tool_registry = tool_registry
        self._max_tool_rounds = max_tool_rounds
        self._graph = None


    @observe(as_type="span", name="agent.graph_run")
    async def ainvoke(self, messages: Sequence[HumanMessage | AIMessage], customer_id: Optional[str] = None,
                      repo: Optional[ChatRepository]= None, session_id: Optional[str] = None,
                      owner_email: Optional[str] = None, ) -> Tuple[str, Optional[str]]:
        
        await self.ensure_graph()

        state_in = {"messages": list(messages), "customer_id": customer_id, "tool_rounds": 0,
                    "repo": repo, "session_id": session_id, "owner_email": owner_email,
                    "should_clear": False, "run_clear_check": False, "tool_cache": {},
                    "blocked": False, "should_summarize": False,
                    "cache_hit": False, "cached_response": None}

        langfuse_handler = CallbackHandler()
        out = await self._graph.ainvoke(state_in, config={"callbacks": [langfuse_handler]})

        out_msgs = list(out.get("messages") or [])
        text = AIHelper._last_ai_text(out_msgs)

        lf = get_client()
        trace_id = lf.get_current_trace_id()
        trace_id_str = str(trace_id) if trace_id else None

        return text, trace_id_str

    async def ensure_graph(self) -> None:
        if self._graph is not None:
            return
        self._graph = await build_fintech_graph(self._tool_registry, self._max_tool_rounds)

    @observe(as_type="span", name="agent.graph_stream")
    async def astream(self, messages: Sequence[HumanMessage | AIMessage], customer_id: Optional[str] = None,
                      repo: Optional[ChatRepository] = None, session_id: Optional[str] = None,
                      owner_email: Optional[str] = None) -> AsyncIterator[Tuple[str, Optional[str]]]:

        await self.ensure_graph()

        state_in = {"messages": list(messages), "customer_id": customer_id, "tool_rounds": 0,
                    "repo": repo, "session_id": session_id, "owner_email": owner_email,
                    "should_clear": False, "run_clear_check": False, "tool_cache": {},
                    "blocked": False, "should_summarize": False,
                    "cache_hit": False, "cached_response": None}

        langfuse_handler = CallbackHandler()

        async for event in self._graph.astream_events(state_in, config={"callbacks": [langfuse_handler]}, version="v2"):
            kind = event.get("event")
            metadata = event.get("metadata", {})
            langgraph_node = metadata.get("langgraph_node", "")

            # Stream from agent node (normal flow)
            if kind == "on_chat_model_stream" and langgraph_node == "agent":
                chunk = event.get("data", {}).get("chunk")
                if chunk and hasattr(chunk, "content") and chunk.content:
                    yield chunk.content, None

            # Stream from return_cached node (cache hit)
            if kind == "on_chain_end" and langgraph_node == "return_cached":
                output = event.get("data", {}).get("output", {})
                messages_out = output.get("messages", [])
                if messages_out:
                    last_msg = messages_out[-1]
                    if hasattr(last_msg, "content") and last_msg.content:
                        yield last_msg.content, None

            # Stream from safety_guard node (blocked queries)
            if kind == "on_chain_end" and langgraph_node == "safety_guard":
                output = event.get("data", {}).get("output")
                if isinstance(output, dict) and output.get("blocked"):
                    messages_out = output.get("messages", [])
                    if messages_out:
                        last_msg = messages_out[-1]
                        if hasattr(last_msg, "content") and last_msg.content:
                            yield last_msg.content, None

        lf = get_client()
        trace_id = lf.get_current_trace_id()
        trace_id_str = str(trace_id) if trace_id else None
        yield "", trace_id_str

