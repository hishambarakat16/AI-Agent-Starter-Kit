# app/MCP/policy_server.py
from __future__ import annotations

from typing import Literal

from pathlib import Path
from MCP.server.logging_config import configure_logging
from langfuse import observe

configure_logging(
    config_path=Path(__file__).resolve().parent / "logging.yaml",
    logs_dir=Path("logs/mcp"),
)


from mcp.server.fastmcp import FastMCP
from MCP.server.env import get_host, get_port

from app.retrieval.models import PolicyFilters
from app.retrieval.rerank import RerankConfig
from app.retrieval.retriever import PolicyDocsRetriever

from .error_handling import run_tool, norm_bool, norm_int, norm_float, norm_str

from functools import lru_cache
from app.retrieval.query_translation import QueryTranslator
from app.retrieval.models import QueryTranslationConfig, PolicyHit
from app.retrieval.http_reranker import HTTPRerankerBackend
from MCP.server.langfuse_trace_middleware import LangfuseMCPTraceJoinMiddleware
from .mcp_trace_context import get_trace_context
from langfuse import get_client

mcp = FastMCP(name="policy-retrieval",
    host=get_host(),
    port=get_port(8052),
    stateless_http=True,
)
# app = mcp.streamable_http_app()
_inner_app = mcp.streamable_http_app()
app = LangfuseMCPTraceJoinMiddleware(_inner_app)

@mcp.tool()
def rewrite_query_with_options(
    question: str,
    mode: Literal["basic", "expanded", "full", "custom"] = "basic",
    enable_multi_query: bool | None = None,
    enable_decomposition: bool | None = None,
    enable_step_back: bool | None = None,
    multi_query_k: int | None = 3,
    max_sub_questions: int | None = 3,
    cache_enabled: bool | None = True,
    cache_min_similarity: float | None = 0.85,
    cache_persist_directory: str | None = "./.local_cache/query_translation",
) -> dict:
    """
    Rewrite a user question into retrieval queries for policy/contract lookup.

    This tool DOES NOT answer questions and DOES NOT contain policy knowledge.
    Use it only to generate retrieval-friendly queries that will be passed to
    policy_retrieve. Always follow with policy_retrieve (and optional rerank)
    before answering.

    When to use:
    - The user query is vague, slangy, emotional, or poorly specified.
    - You need a contract-style phrasing for better retrieval.

    When NOT to use:
    - If you already have relevant retrieved passages for the current topic.
    - If the user is asking for an explanation of retrieved content (summarize instead).

    Modes:
    - basic: single clean rewrite
    - expanded: rewrite + paraphrase variants
    - full: rewrite + variants + decomposition + step-back
    - custom: use enable_* flags

    Tool-call:
    You may omit optional parameters; missing/null values are treated as defaults.
    """

    tool_name = "policy_translate_query"
    trace_context = get_trace_context()
    langfuse = get_client()
    def _impl() -> dict:
        # ---- normalize primitives first (prevents int(None), float(None), etc.) ----
        _mode = norm_str(mode, "basic")

        _enable_multi_query = norm_bool(enable_multi_query, False)
        _enable_decomposition = norm_bool(enable_decomposition, False)
        _enable_step_back = norm_bool(enable_step_back, False)

        _multi_query_k = norm_int(multi_query_k, 3)
        _max_sub_questions = norm_int(max_sub_questions, 3)

        _cache_enabled = norm_bool(cache_enabled, True)
        _cache_min_similarity = norm_float(cache_min_similarity, 0.85)
        _cache_persist_directory = norm_str(cache_persist_directory, "./.local_cache/query_translation")

        mq, decomp, step = resolve_translation_toggles(
            mode=_mode,
            enable_multi_query=_enable_multi_query,
            enable_decomposition=_enable_decomposition,
            enable_step_back=_enable_step_back,
        )

        if not mq:
            _multi_query_k = 0
        if not decomp:
            _max_sub_questions = 0

        translator = get_translator_cached(
            enabled=True,
            enable_multi_query=bool(mq),
            enable_decomposition=bool(decomp),
            enable_step_back=bool(step),
            multi_query_k=int(_multi_query_k),
            max_sub_questions=int(_max_sub_questions),
            cache_enabled=bool(_cache_enabled),
            cache_min_similarity=float(_cache_min_similarity),
            cache_persist_directory=str(_cache_persist_directory),
        )

        res = translator.translate(question)

        # Prefer canonical helper if present; otherwise build deterministically.
        queries_for_retrieval: list[str]
        if hasattr(res, "all_queries_for_retrieval"):
            try:
                queries_for_retrieval = list(res.all_queries_for_retrieval())  # type: ignore[attr-defined]
            except Exception:
                queries_for_retrieval = []
        else:
            queries_for_retrieval = []

        if not queries_for_retrieval:
            candidates: list[str] = []
            if (res.rewritten_question or "").strip():
                candidates.append(res.rewritten_question.strip())
            for x in (res.rewrites or []):
                x = (x or "").strip()
                if x:
                    candidates.append(x)
            for x in (res.sub_questions or []):
                x = (x or "").strip()
                if x:
                    candidates.append(x)
            if (res.step_back_question or "").strip():
                candidates.append(res.step_back_question.strip())

            seen: set[str] = set()
            queries_for_retrieval = []
            for c in candidates:
                key = " ".join(c.lower().split())
                if key and key not in seen:
                    seen.add(key)
                    queries_for_retrieval.append(c)

        return {
            "mode": _mode,
            "original_question": res.original_question,
            "rewritten_question": res.rewritten_question,
            "rewrites": res.rewrites,
            "sub_questions": res.sub_questions,
            "step_back_question": res.step_back_question,
            "queries_for_retrieval": queries_for_retrieval,
            "cache_enabled": bool(_cache_enabled),
            "cache_min_similarity": float(_cache_min_similarity),
            "cache_persist_directory": str(_cache_persist_directory),
            # Optional: echo resolved toggles (useful when debugging)
            "resolved": {
                "enable_multi_query": bool(mq),
                "enable_decomposition": bool(decomp),
                "enable_step_back": bool(step),
                "multi_query_k": int(_multi_query_k),
                "max_sub_questions": int(_max_sub_questions),
            },
        }

    # Echo *raw* inputs (not normalized) so you can see what the tool actually received.
    input_echo = {
        "question": question,
        "mode": mode,
        "enable_multi_query": enable_multi_query,
        "enable_decomposition": enable_decomposition,
        "enable_step_back": enable_step_back,
        "multi_query_k": multi_query_k,
        "max_sub_questions": max_sub_questions,
        "cache_enabled": cache_enabled,
        "cache_min_similarity": cache_min_similarity,
        "cache_persist_directory": cache_persist_directory,
    }

    with langfuse.start_as_current_observation( as_type="span", name="LangGraph", trace_context=trace_context, input=input_echo) as span:
        out = run_tool(tool_name, _impl, input_echo=input_echo)
    return out



@mcp.tool()
def policy_retrieve(query: str, lang: str = "en", top_k: int = 8, min_top_score: float = 0.78, min_margin: float = 0.08) -> dict:
    """
    Retrieve top_k policy chunks for a query (NO rerank performed here).

    Args:
        query: User question or search text. (required)
        lang: Language of policy text ("en", "ar"). Default "en".
        top_k: Number of chunks to retrieve. Default 8.
        min_top_score: Threshold for rerank trigger. Default 0.78.
        min_margin: Margin threshold for rerank trigger. Default 0.08.

    Tool-call rule:
        Always pass ALL arguments explicitly in tool calls
        (query, lang, top_k, min_top_score, min_margin). Do not send null/None.

    Returns:
        Dict containing query, lang, top_k, hits, and signals.
    """
    input_echo = {
        "query": query,
        "lang": lang,
        "top_k": top_k,
        "min_top_score": min_top_score,
        "min_margin": min_margin,
    }

    langfuse = get_client()
    trace_context = get_trace_context()

    with langfuse.start_as_current_observation(as_type="span", name="LangGraph", trace_context=trace_context, input=input_echo) as span:
        retriever = PolicyDocsRetriever(rerank_cfg=RerankConfig(enabled=False), use_bge_reranker=False)

        hits = retriever.hybrid_search(query=query, top_k=top_k, filters=PolicyFilters(lang=lang))
        hits_dicts = [hit_to_dict(h) for h in hits]

        cfg = RerankConfig(enabled=True, min_top_score=float(min_top_score), min_margin=float(min_margin))

        if not hits_dicts:
            s1 = 0.0
            s2 = 0.0
            margin = 0.0
        else:
            scores = sorted((base_score_dict(h) for h in hits_dicts), reverse=True)
            s1 = float(scores[0])
            s2 = float(scores[1]) if len(scores) > 1 else 0.0
            margin = float(s1 - s2)

        out = {
            "query": query,
            "lang": lang,
            "top_k": int(top_k),
            "hits": hits_dicts,
            "signals": {
                "top_score": float(s1),
                "second_score": float(s2),
                "margin": float(margin),
                "rerank_trigger_cfg": {"min_top_score": float(cfg.min_top_score), "min_margin": float(cfg.min_margin)},
                "suggest_rerank": bool((s1 < cfg.min_top_score) or (margin < cfg.min_margin)),
            },
        }

        span.update(output=out)
        return out



@mcp.tool()
def rerank_retreivals(query: str, hits: list[dict]) -> dict:
    """
    Rerank previously retrieved policy hits for a query.

    Required inputs:
      - query (str): the user question / search text.
      - hits (list[dict]): items must include:
          * id (or doc_id)
          * text (or page_content)

    Output:
      - dict: reranker backend response (reranked hits + scores, backend-dependent).
    """
    input_echo = {"query": query, "hits_count": len(hits or [])}

    langfuse = get_client()
    trace_context = get_trace_context()

    with langfuse.start_as_current_observation(as_type="span", name="LangGraph", trace_context=trace_context, input=input_echo) as span:
        backend = HTTPRerankerBackend()

        rr_hits: list[dict] = []
        for h in (hits or []):
            _id = h.get("id") or h.get("doc_id")
            _text = h.get("text") or h.get("page_content")
            if not _id or not _text:
                continue
            rr_hits.append({"id": str(_id), "text": str(_text)})

        out = backend.rerank(query=query, hits=rr_hits)

        span.update(output={"hits_in": len(hits or []), "hits_sent": len(rr_hits), "result": out})
        return out




def resolve_translation_toggles(
    mode: str,
    enable_multi_query: bool | None,
    enable_decomposition: bool | None,
    enable_step_back: bool | None,
) -> tuple[bool, bool, bool]:
    if mode == "basic":
        mq, decomp, step = (False, False, False)
    elif mode == "expanded":
        mq, decomp, step = (True, False, False)
    elif mode == "full":
        mq, decomp, step = (True, True, True)
    else:
        mq, decomp, step = (False, False, False)

    if enable_multi_query is not None:
        mq = bool(enable_multi_query)
    if enable_decomposition is not None:
        decomp = bool(enable_decomposition)
    if enable_step_back is not None:
        step = bool(enable_step_back)

    return mq, decomp, step


@lru_cache(maxsize=16)
def get_translator_cached(
    enabled: bool,
    enable_multi_query: bool,
    enable_decomposition: bool,
    enable_step_back: bool,
    multi_query_k: int,
    max_sub_questions: int,
    cache_enabled: bool,
    cache_min_similarity: float,
    cache_persist_directory: str,
) -> QueryTranslator:
    cfg = QueryTranslationConfig(
        enabled=enabled,
        enable_multi_query=enable_multi_query,
        multi_query_k=multi_query_k,
        enable_decomposition=enable_decomposition,
        max_sub_questions=max_sub_questions,
        enable_step_back=enable_step_back,
        cache_enabled=cache_enabled,
        cache_min_similarity=cache_min_similarity,
        cache_persist_directory=cache_persist_directory,
    )
    return QueryTranslator(cfg)


def hit_to_dict(h: PolicyHit) -> dict:
    return {
        "doc_id": getattr(h, "doc_id", ""),
        "page_content": getattr(h, "page_content", ""),
        "lang": getattr(h, "lang", ""),
        "source": getattr(h, "source", ""),
        "page": getattr(h, "page", 0),
        "page_column": getattr(h, "page_column", ""),
        "pair_id": getattr(h, "pair_id", ""),
        "chunk_index": getattr(h, "chunk_index", 0),
        "questions": list(getattr(h, "questions", None) or []),
        "metadata": getattr(h, "metadata", None),
        "ingest_dir": getattr(h, "ingest_dir", ""),
        "question_score": float(getattr(h, "question_score", 0.0) or 0.0),
        "dense_score": float(getattr(h, "dense_score", 0.0) or 0.0),
        "sparse_score": float(getattr(h, "sparse_score", 0.0) or 0.0),
        "hybrid_score": float(getattr(h, "hybrid_score", 0.0) or 0.0),
        "rerank_score": float(getattr(h, "rerank_score", 0.0) or 0.0),
    }


def base_score_dict(d: dict) -> float:
    return max(
        float(d.get("question_score") or 0.0),
        float(d.get("hybrid_score") or 0.0),
        float(d.get("dense_score") or 0.0),
        float(d.get("sparse_score") or 0.0),
    )




if __name__ == "__main__":
    mcp.run(transport="streamable-http")
