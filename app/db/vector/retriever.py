"""
Document Retriever — high-level interface used by the MCP vector server.

This is what MCP/server/vector_server.py calls. It wraps the low-level
query functions (queries.py) with:
  - Embedding caching (same query → same vector, no redundant API calls)
  - Score normalization (so dense and sparse scores are comparable)
  - Hybrid search orchestration
  - Optional reranking via maybe_rerank()

Usage in your MCP vector server:
  from app.db.vector.retriever import DocumentRetriever
  from app.db.vector.models import DocumentFilters, RerankConfig

  retriever = DocumentRetriever()
  hits = retriever.search(query="what is the return policy?", top_k=8)
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import List, Optional

from langfuse import observe

from .models import DocumentFilters, DocumentHit, RerankConfig, VectorSearchConfig
from .queries import hybrid_search
from .rerank import NoOpRerankerBackend, RerankerBackend, maybe_rerank

log = logging.getLogger(__name__)


# ─── Embedding cache ──────────────────────────────────────────────────────────
# Embedding the same query string twice in one request is wasteful.
# lru_cache keeps the last 1024 unique query strings in memory.
# Returns a tuple (hashable) so the cache key works correctly.

@lru_cache(maxsize=1024)
def _embed_cached(query: str) -> tuple:
    from app.utils.connect_db import get_embedder  # late import — avoids circular deps
    vec = get_embedder().embed_query(query)
    return tuple(vec)


# ─── Retriever ────────────────────────────────────────────────────────────────

class DocumentRetriever:
    """
    High-level retriever used by the MCP vector server.

    Instantiate once per server process (stateless, thread-safe).
    All configuration is passed per-call so it can be overridden by the
    MCP tool's arguments without creating a new instance.
    """

    def __init__(
        self,
        *,
        rerank_cfg: Optional[RerankConfig] = None,
        reranker: Optional[RerankerBackend] = None,
        table: str = "document_chunks",
    ) -> None:
        self.rerank_cfg = rerank_cfg or RerankConfig(enabled=False)
        self.reranker = reranker or NoOpRerankerBackend()
        self.table = table

    @observe(as_type="span", name="retriever.search")
    def search(
        self,
        *,
        query: str,
        top_k: int = 8,
        filters: Optional[DocumentFilters] = None,
        cfg: Optional[VectorSearchConfig] = None,
    ) -> List[DocumentHit]:
        """
        Hybrid search + optional rerank.

        1. Embed the query (cached)
        2. Dense + sparse search (candidates)
        3. Score normalization + fusion
        4. Rerank if retrieval looks uncertain (based on RerankConfig thresholds)

        Returns top_k DocumentHit objects sorted by best available score.
        """
        filters = filters or DocumentFilters()
        cfg = cfg or VectorSearchConfig(top_k=top_k)

        query_vec = list(_embed_cached(query))

        from app.utils.connect_db import get_conn  # late import
        conn = get_conn()
        try:
            hits = hybrid_search(
                conn,
                query_text=query,
                query_vec=query_vec,
                top_k=cfg.top_k,
                dense_k=cfg.dense_k,
                sparse_k=cfg.sparse_k,
                alpha=cfg.alpha,
                filters=filters,
                table=self.table,
            )
        finally:
            conn.close()

        return maybe_rerank(
            query=query,
            hits=hits,
            cfg=self.rerank_cfg,
            reranker=self.reranker,
        )

    def hits_to_dicts(self, hits: List[DocumentHit]) -> List[dict]:
        """Serialize hits to plain dicts for the MCP tool response."""
        return [
            {
                "id":           h.doc_id,
                "text":         h.text,
                "source":       h.source,
                "metadata":     h.metadata,
                "dense_score":  round(h.dense_score, 4),
                "sparse_score": round(h.sparse_score, 4),
                "hybrid_score": round(h.hybrid_score, 4),
                "rerank_score": round(h.rerank_score, 4),
            }
            for h in hits
        ]
