"""
MCP Vector Server — Template for vector/RAG document retrieval.

This file shows the PATTERN for exposing semantic search as MCP tools.
The agent calls these tools to find relevant document chunks before
answering policy, knowledge-base, or FAQ-type questions.

Pattern the agent follows (defined in the system prompt):
  1. rewriteQuery    — optional: rephrase the question for better retrieval
  2. retrieveChunks  — vector similarity search → top-K chunks
  3. rerankChunks    — optional: re-score chunks by relevance
  4. answer          — LLM synthesizes answer from retrieved chunks

You plug in your own vector database in the data layer at the bottom.
The MCP → LangChain → agent wiring is already handled.

How it connects to the agent:
  vector_server.py (FastMCP tools)
       ↓  HTTP POST /mcp
  MCPServerClient  (app/integrations/mcp/core.py)
       ↓  MCPCallResult.text (JSON string)
  MCPToolRegistry  (app/integrations/mcp/tool_registry.py)
       ↓  StructuredTool (LangChain format)
  LangGraph agent  (app/graphs/fintech_graph.py)
       ↓  tool result injected as ToolMessage
  LLM synthesizes answer from chunks
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP
from langfuse import get_client

from MCP.server.env import get_host, get_port
from MCP.server.langfuse_trace_middleware import LangfuseMCPTraceJoinMiddleware
from MCP.server.logging_config import configure_logging
from .mcp_trace_context import get_trace_context

configure_logging(
    config_path=Path(__file__).resolve().parent / "logging.yaml",
    logs_dir=Path("logs/mcp"),
)
logger = logging.getLogger("mcp_vector")

# ─── FastMCP setup ────────────────────────────────────────────────────────────
mcp = FastMCP(
    name="vector-retrieval",
    host=get_host(),
    port=get_port(8052),
    stateless_http=True,
)
_inner_app = mcp.streamable_http_app()
app = LangfuseMCPTraceJoinMiddleware(_inner_app)


# ─── Tool definitions ─────────────────────────────────────────────────────────

@mcp.tool()
def rewriteQuery(question: str, mode: str = "basic") -> dict:
    """
    Rewrite a user question into retrieval-friendly queries.

    Use this when the user's question is vague, conversational, or would
    benefit from rephrasing before vector search. Do NOT use if you already
    have retrieved chunks for the current topic.

    Args:
        question: The user's original question. (required)
        mode:     Rewrite strategy.
                  - "basic"    → single clean rewrite (default)
                  - "expanded" → rewrite + paraphrase variants
                  - "full"     → rewrite + variants + sub-questions + step-back

    Returns:
        dict with:
          - original_question (str)
          - rewritten_question (str)
          - queries_for_retrieval (list[str])  ← pass these to retrieveChunks
    """
    logger.info("rewriteQuery mode=%s question=%s", mode, question[:80])
    input_echo = {"question": question, "mode": mode}

    langfuse = get_client()
    trace_context = get_trace_context()

    with langfuse.start_as_current_observation(
        as_type="span", name="mcp:rewriteQuery",
        trace_context=trace_context, input=input_echo,
    ) as span:
        result = _rewrite_query(question, mode)
        span.update(output=result)
        return result


@mcp.tool()
def retrieveChunks(query: str, top_k: int = 8, filter_tag: Optional[str] = None) -> dict:
    """
    Search the knowledge base for chunks relevant to a query.

    Args:
        query:      The search query (use output of rewriteQuery or raw question). (required)
        top_k:      Number of chunks to return. Default 8.
        filter_tag: Optional metadata filter (e.g. "faq", "policy", "en"). Default None.

    Returns:
        dict with:
          - query (str)
          - top_k (int)
          - hits (list[dict])  — each hit has: id, text, score, source, metadata
          - signals (dict)     — top_score, margin, suggest_rerank (bool)

    If signals.suggest_rerank is True, consider calling rerankChunks before answering.
    """
    logger.info("retrieveChunks query=%s top_k=%d", query[:80], top_k)
    input_echo = {"query": query, "top_k": top_k, "filter_tag": filter_tag}

    langfuse = get_client()
    trace_context = get_trace_context()

    with langfuse.start_as_current_observation(
        as_type="span", name="mcp:retrieveChunks",
        trace_context=trace_context, input=input_echo,
    ) as span:
        hits = _vector_search(query, top_k, filter_tag)

        # Compute signals so agent can decide whether reranking is worthwhile
        scores = sorted([h.get("score", 0.0) for h in hits], reverse=True)
        top_score = float(scores[0]) if scores else 0.0
        second_score = float(scores[1]) if len(scores) > 1 else 0.0
        margin = top_score - second_score

        result = {
            "query": query,
            "top_k": top_k,
            "hits": hits,
            "signals": {
                "top_score": top_score,
                "margin": margin,
                # Agent uses this hint to decide whether to call rerankChunks
                "suggest_rerank": top_score < 0.78 or margin < 0.08,
            },
        }
        span.update(output={"hit_count": len(hits), "top_score": top_score})
        return result


@mcp.tool()
def rerankChunks(query: str, hits: list[dict]) -> dict:
    """
    Re-score retrieved chunks by relevance to the query.

    Call this after retrieveChunks when signals.suggest_rerank is True,
    or when the top hits feel too similar in score to trust the ordering.

    Args:
        query: The search query. (required)
        hits:  List of hit dicts from retrieveChunks (must include 'id' and 'text'). (required)

    Returns:
        dict with reranked hits in descending relevance order.
    """
    logger.info("rerankChunks query=%s hits=%d", query[:80], len(hits or []))
    input_echo = {"query": query, "hits_count": len(hits or [])}

    langfuse = get_client()
    trace_context = get_trace_context()

    with langfuse.start_as_current_observation(
        as_type="span", name="mcp:rerankChunks",
        trace_context=trace_context, input=input_echo,
    ) as span:
        result = _rerank(query, hits or [])
        span.update(output={"hits_out": len(result.get("hits", []))})
        return result


# ─── YOUR VECTOR DATA LAYER ───────────────────────────────────────────────────
# Replace these three functions with your actual vector DB / reranker calls.
#
# Vector databases that work well here:
#   - pgvector (PostgreSQL extension) — what we used in the main project
#   - Chroma   — lightweight, great for local dev
#   - Pinecone — managed, production-scale
#   - Weaviate — hybrid search built-in
#   - Qdrant   — fast, self-hostable
#   - Azure AI Search — if you're on Azure
#
# Each hit dict returned by _vector_search should look like:
#   {
#     "id":       str,    # unique chunk ID
#     "text":     str,    # the chunk content the LLM will read
#     "score":    float,  # similarity score (0–1)
#     "source":   str,    # document name / filename
#     "metadata": dict,   # any extra metadata (page, section, language, etc.)
#   }

def _rewrite_query(question: str, mode: str) -> dict:
    """
    Replace with your query rewriting logic.

    Simple approach: just return the question as-is.
    Better approach: call an LLM to rephrase for retrieval.

    Example with OpenAI:
        from openai import OpenAI
        client = OpenAI()
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Rewrite the question for document search."},
                {"role": "user", "content": question},
            ]
        )
        rewritten = response.choices[0].message.content.strip()
        return {
            "original_question": question,
            "rewritten_question": rewritten,
            "queries_for_retrieval": [rewritten],
        }
    """
    # Minimal passthrough — replace with real logic
    return {
        "original_question": question,
        "rewritten_question": question,
        "queries_for_retrieval": [question],
    }


def _vector_search(query: str, top_k: int, filter_tag: Optional[str]) -> list[dict]:
    """
    Replace with your vector DB similarity search.

    Example with pgvector (PostgreSQL):
        import psycopg2
        from openai import OpenAI

        openai = OpenAI()
        embedding = openai.embeddings.create(
            model="text-embedding-3-small", input=query
        ).data[0].embedding

        with psycopg2.connect(...) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    '''
                    SELECT id, text, source, metadata,
                           1 - (embedding <=> %s::vector) AS score
                    FROM document_chunks
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                    ''',
                    (embedding, embedding, top_k)
                )
                rows = cur.fetchall()

        return [
            {"id": str(r[0]), "text": r[1], "source": r[2],
             "metadata": r[3], "score": float(r[4])}
            for r in rows
        ]

    Example with Chroma:
        import chromadb
        client = chromadb.Client()
        collection = client.get_collection("my_docs")
        results = collection.query(query_texts=[query], n_results=top_k)
        ...
    """
    raise NotImplementedError("Connect your vector database here.")


def _rerank(query: str, hits: list[dict]) -> dict:
    """
    Replace with your reranker.

    Options:
    - BGE reranker via HTTP (what we used): POST to a local reranker service
    - Cohere rerank API
    - Cross-encoder model via sentence-transformers
    - Skip reranking entirely and just return hits as-is

    Minimal passthrough (no reranking):
        return {"hits": hits}
    """
    # Passthrough — replace with real reranker
    return {"hits": hits}


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
