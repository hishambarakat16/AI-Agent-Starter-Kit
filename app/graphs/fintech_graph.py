# app/graphs/fintech_graph.py
from __future__ import annotations

import json
import logging
from typing import Annotated, Optional, Sequence, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

from app.integrations.mcp import MCPToolRegistry
from app.repository import ChatRepository
from app.prompts.graph_prompts import DEFAULT_GRAPH_PROMPT, FOLLOWUP_PROMPT
from app.utils import Utils, AsyncHelper, AIHelper
from app.cache.semantic_cache import QuerySemanticCache
from .llm_gaurd import LLMGuard

CLEAR_CHECK_MIN_HUMAN_TURNS = 3
CLEAR_KEEP_LAST = 12
SUMMARIZE_THRESHOLD = 12  # Summarize after ~6 turns (realistic for support)
SUMMARIZE_KEEP_RECENT = 6
logger = logging.getLogger("graphs")


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    customer_id: Optional[str]
    tool_rounds: int
    repo: Optional[ChatRepository]
    session_id: Optional[str]
    owner_email: Optional[str]
    should_clear: bool
    run_clear_check: bool
    tool_cache: dict[str, str]
    blocked: bool
    should_summarize: bool
    cache_hit: bool  # NEW: Track if response came from cache
    cached_response: Optional[str]  # NEW: Store cached response


async def build_fintech_graph(
    tool_registry: MCPToolRegistry,
    max_tool_rounds: int = 6,
    enable_semantic_cache: bool = True,
    cache_distance_threshold: float = 0.05,
):
    import os

    tools = await tool_registry.get_tools()

    model = ChatOpenAI( model=DEFAULT_GRAPH_PROMPT["model"], temperature=DEFAULT_GRAPH_PROMPT["temperature"]).bind_tools(tools)
    followup_model = ChatOpenAI(model=FOLLOWUP_PROMPT["model"], temperature=FOLLOWUP_PROMPT["temperature"])
    summarize_model = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    cache_classifier_model = ChatOpenAI(model="gpt-4o-mini", temperature=0)

    system_template = DEFAULT_GRAPH_PROMPT["prompt"]
    followup_template = FOLLOWUP_PROMPT["prompt"]

    tool_by_name = {t.name: t for t in tools}

    # Allow env var override for distance threshold
    threshold = float(os.getenv("SEMANTIC_CACHE_DISTANCE_THRESHOLD", str(cache_distance_threshold)))
    semantic_cache = (QuerySemanticCache(distance_threshold=threshold) if enable_semantic_cache else None)

    def cache_key(name: str, args: dict) -> str:
        return f"{name}:{json.dumps(args, sort_keys=True, ensure_ascii=False, separators=(',', ':'))}"

    async def semantic_cache_lookup_node(state: AgentState) -> AgentState:
        """
        Use LLM to classify if query is a standalone policy Q&A question.
        If yes and cache hit, return cached response.
        Otherwise proceed to agent.
        """
        if not semantic_cache:
            return {"cache_hit": False, "cached_response": None}

        msgs = list(state.get("messages") or [])
        if not msgs:
            return {"cache_hit": False, "cached_response": None}

        # Get the last human message as the query
        last_msg = msgs[-1]
        if not isinstance(last_msg, HumanMessage):
            return {"cache_hit": False, "cached_response": None}

        query = last_msg.content
        customer_id = state.get("customer_id")

        # Classify query type and check if it's standalone (supports English and Arabic)
        classification_prompt = f"""Classify this user query into ONE category. Read carefully:

POLICY: Questions about bank policies, procedures, fees, security, or general banking topics. These questions are COMPLETE and don't use pronouns referring to prior context.
  Examples that ARE policy questions:
  - "What if I got hacked? How do I get my money back?"
  - "Can I withdraw early?"
  - "What are the fees?"
  - "How do I report fraud?"
  - "What happens if my account is compromised?"
  - "Is there a minimum balance?"

PERSONALIZED: Questions about THIS SPECIFIC user's account data, transactions, or balance.
  Examples:
  - "Show my transactions"
  - "What's my balance?"
  - "Get my profile"

FOLLOWUP: Questions using pronouns (it, that, this, them, those) referring to something mentioned earlier, OR asking to elaborate on a previous response.
  Examples that ARE follow-ups (notice the pronouns):
  - "What does THAT mean?"
  - "Can you explain IT more?"
  - "Tell me about the second one"
  - "What about THEM?"

User query: "{query}"

Think: Does this query use pronouns referring to prior context? If NO, it's likely POLICY.

Respond with ONLY one word: POLICY, PERSONALIZED, or FOLLOWUP"""

        try:
            classification_result = await cache_classifier_model.ainvoke(classification_prompt)
            classification = (classification_result.content or "").strip().upper()

            if classification in ("PERSONALIZED", "FOLLOWUP"):
                logger.info("Query classified as %s - skipping cache query=%s", classification, query[:50])
                return {"cache_hit": False, "cached_response": None}

            # Query is POLICY - check cache
            logger.info("Query classified as POLICY - checking cache query=%s", query[:50])
            cached = await semantic_cache.lookup(query, customer_id)

            if cached:
                logger.info("Semantic cache HIT - returning cached response query=%s", query[:50])
                return {"cache_hit": True, "cached_response": cached}

            logger.info("Semantic cache MISS - proceeding to agent query=%s", query[:50])
            return {"cache_hit": False, "cached_response": None}

        except Exception as e:
            logger.error("Cache classification failed error=%s - proceeding to agent", str(e))
            return {"cache_hit": False, "cached_response": None}

    async def cache_response_node(state: AgentState) -> AgentState:
        """
        Store the agent's response in the semantic cache.
        Only caches policy responses (not SQL/personalized queries).
        """
        if not semantic_cache:
            return {}

        msgs = list(state.get("messages") or [])
        if len(msgs) < 2:
            return {}

        # Check if policy tools were used (check AIMessage tool_calls, not ToolMessage content)
        policy_tool_names = []
        for msg in msgs[-10:]:
            if isinstance(msg, AIMessage) and msg.tool_calls:
                policy_tool_names.extend([tc.get("name", "") for tc in msg.tool_calls if tc.get("name", "").startswith("policy_")])

        used_policy_tools = len(policy_tool_names) > 0

        if not used_policy_tools:
            logger.info("Skipping cache - no policy tools used in this response")
            return {}

        logger.info("Policy tools detected for caching: %s", policy_tool_names)

        last_ai = None
        last_human = None

        for msg in reversed(msgs):
            if isinstance(msg, AIMessage) and not last_ai:
                last_ai = msg
            elif isinstance(msg, HumanMessage) and not last_human:
                last_human = msg

            if last_ai and last_human:
                break

        if not (last_ai and last_human):
            return {}

        query = last_human.content
        response = last_ai.content
        customer_id = state.get("customer_id")

        # Store in cache (runs synchronously but fast - just Redis write)
        # We already verified this is a policy question in semantic_cache_lookup_node
        if not last_ai.tool_calls and response and isinstance(response, str) and len(response.strip()) > 0:
            try:
                await semantic_cache.store(query, response, customer_id)
                logger.info("Cached policy response query=%s response_len=%d", query[:50], len(response))
            except Exception as e:
                logger.error("Cache storage failed error=%s", str(e))
        else:
            if last_ai.tool_calls:
                logger.info("Skipping cache - AI message has pending tool calls")
            else:
                logger.info("Skipping cache - AI response is empty or invalid")

        return {}

    def gate_cache(state: AgentState) -> str:
        """Route based on cache hit."""
        if state.get("cache_hit"):
            return "return_cached"
        return "clear_check_buffer"

    async def return_cached_response_node(state: AgentState) -> AgentState:
        """Return the cached response as an AI message."""
        cached = state.get("cached_response", "")
        msgs = list(state.get("messages") or [])

        ai_msg = AIMessage(content=cached)
        return {"messages": msgs + [ai_msg]}

    async def decide_clear_node(state: AgentState) -> AgentState:
        messages = list(state["messages"])
        recent = messages[-6:]
        chain = followup_template | followup_model
        out = await chain.ainvoke({"history": recent})
        decision = (out.content or "").strip().upper()
        return {"should_clear": decision == "NEW"}

    async def clear_history_node(state: AgentState) -> AgentState:
        msgs = list(state.get("messages") or [])
        kept = msgs[-CLEAR_KEEP_LAST:] if len(msgs) > CLEAR_KEEP_LAST else msgs
        return {
            "messages": kept,
            "tool_cache": {},
            "tool_rounds": 0,
            "should_clear": False,
            "run_clear_check": False,
        }

    async def safety_guard_node(state: AgentState) -> AgentState:
        msgs = list(state.get("messages") or [])

        if LLMGuard.should_block_identity_lookup(msgs):
            return {
                "messages": msgs + [LLMGuard.make_block_ai_message()],
                "blocked": True,
            }

        return {"blocked": False}

    def gate_identity(state: AgentState) -> str:
        return "end" if state.get("blocked") else "semantic_cache_lookup"

    async def agent_node(state: AgentState) -> AgentState:
        messages = list(state["messages"])
        chain = system_template | model
        ai = await chain.ainvoke({"history": messages})
        if isinstance(ai, AIMessage) and ai.content:
            ai.content = AIHelper.redact_customer_id_output(ai.content)

        return {"messages": messages + [ai]}

    async def tools_node(state: AgentState) -> AgentState:
        rounds, out, customer_id, tool_calls = AIHelper.tool_step_inputs(state)
        logger.info(
            "tools step start tool_rounds=%d tool_calls=%d", rounds, len(tool_calls)
        )

        cache = dict(state.get("tool_cache") or {})

        for tc in tool_calls:
            name = tc["name"]
            args = AIHelper.normalize_tool_args(name, tc.get("args") or {}, customer_id)
            key = cache_key(name, args)

            if key in cache:
                logger.info("tools cache hit name=%s", name)
                out.append(
                    ToolMessage(tool_call_id=str(tc.get("id", name)), content=cache[key])
                )
                continue

            result = await AsyncHelper.run_tool(tool_by_name, name, args, logger)
            content = Utils.jsonify(result)
            cache[key] = content
            out.append(
                ToolMessage(tool_call_id=str(tc.get("id", name)), content=content)
            )

        logger.info(
            "tools step end tool_rounds=%d tool_messages=%d", rounds, len(out)
        )
        msgs = list(state["messages"])
        return {"messages": msgs + out, "tool_rounds": rounds, "tool_cache": cache}

    def route_clear(state: AgentState) -> str:
        return "clear_history" if state.get("should_clear") else "agent"

    def should_continue(state: AgentState) -> str:
        if state["tool_rounds"] >= max_tool_rounds:
            logger.warning(
                "should_continue=max_rounds_reached tool_rounds=%d max_tool_rounds=%d -> cache_response",
                state["tool_rounds"],
                max_tool_rounds,
            )
            return "cache_response"
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and last.tool_calls:
            logger.info("should_continue=tool_calls_present -> tools")
            return "tools"
        logger.info("should_continue=no_tool_calls -> cache_response")
        return "cache_response"

    async def clear_check_buffer_node(state: AgentState) -> AgentState:
        msgs = list(state.get("messages") or [])
        human_turns = sum(1 for m in msgs if isinstance(m, HumanMessage))
        should_summarize = len(msgs) > SUMMARIZE_THRESHOLD
        return {
            "run_clear_check": human_turns >= CLEAR_CHECK_MIN_HUMAN_TURNS,
            "should_clear": False,
            "should_summarize": should_summarize,
            "tool_cache": state.get("tool_cache") or {},
        }

    def gate_clear_check(state: AgentState) -> str:
        if state.get("should_summarize"):
            return "summarize_history"
        return "decide_clear" if state.get("run_clear_check") else "agent"

    async def summarize_history_node(state: AgentState) -> AgentState:
        """Summarize older messages to reduce context size."""
        msgs = list(state.get("messages") or [])

        if len(msgs) <= SUMMARIZE_THRESHOLD:
            return {"should_summarize": False}

        split_point = len(msgs) - SUMMARIZE_KEEP_RECENT
        old_msgs = msgs[:split_point]
        recent_msgs = msgs[split_point:]

        logger.info(
            "summarizing messages total=%d old=%d recent=%d",
            len(msgs),
            len(old_msgs),
            len(recent_msgs),
        )

        conversation_parts = []
        for msg in old_msgs:
            role = "User" if isinstance(msg, HumanMessage) else "Assistant"
            content = (msg.content or "")[:500]
            conversation_parts.append(f"{role}: {content}")

        conversation_text = "\n\n".join(conversation_parts)

        try:
            summary_prompt = f"""Summarize this conversation history concisely. Focus on:
            - Key topics discussed
            - Important facts or data mentioned
            - User's main questions and concerns

            Conversation:
            {conversation_text}

            Concise summary (2-3 sentences):"""

            summary_result = await summarize_model.ainvoke(summary_prompt)
            summary = (summary_result.content or "").strip()

            if not summary:
                logger.warning("summarization returned empty, skipping")
                return {"should_summarize": False}

            summary_msg = HumanMessage(
                content=f"[Previous conversation summary: {summary}]"
            )

            logger.info("summarization complete summary_len=%d", len(summary))

            return {
                "messages": [summary_msg] + recent_msgs,
                "should_summarize": False,
                "tool_cache": {},
            }

        except Exception as e:
            logger.error("summarization failed error=%s", str(e))
            return {"should_summarize": False}

    # Build graph
    graph = StateGraph(AgentState)

    # Add nodes
    graph.add_node("semantic_cache_lookup", semantic_cache_lookup_node)
    graph.add_node("return_cached", return_cached_response_node)
    graph.add_node("safety_guard", safety_guard_node)
    graph.add_node("clear_check_buffer", clear_check_buffer_node)
    graph.add_node("summarize_history", summarize_history_node)
    graph.add_node("decide_clear", decide_clear_node)
    graph.add_node("clear_history", clear_history_node)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tools_node)
    graph.add_node("cache_response", cache_response_node)

    # Set entry point to safety guard (security first!)
    graph.set_entry_point("safety_guard")

    # Route from safety guard
    graph.add_conditional_edges(
        "safety_guard",
        gate_identity,
        {"end": END, "semantic_cache_lookup": "semantic_cache_lookup"},
    )

    # Route from cache lookup
    graph.add_conditional_edges(
        "semantic_cache_lookup",
        gate_cache,
        {"return_cached": "return_cached", "clear_check_buffer": "clear_check_buffer"},
    )

    # Cached response goes straight to end
    graph.add_edge("return_cached", END)

    graph.add_conditional_edges(
        "clear_check_buffer",
        gate_clear_check,
        {
            "summarize_history": "summarize_history",
            "decide_clear": "decide_clear",
            "agent": "agent",
        },
    )
    graph.add_edge("summarize_history", "agent")
    graph.add_conditional_edges(
        "decide_clear", route_clear, {"clear_history": "clear_history", "agent": "agent"}
    )
    graph.add_edge("clear_history", "agent")
    graph.add_conditional_edges(
        "agent",
        should_continue,
        {"tools": "tools", "cache_response": "cache_response"},
    )
    graph.add_edge("tools", "agent")
    graph.add_edge("cache_response", END)

    return graph.compile()