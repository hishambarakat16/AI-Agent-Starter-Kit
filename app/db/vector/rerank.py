"""
Reranker — decides whether to rerank and orchestrates the reranker backend.

Why rerank at all?
  Vector similarity finds semantically related chunks, but "similar" doesn't
  always mean "most relevant to answer this specific question". A cross-encoder
  reranker reads (query, chunk) pairs and scores them more precisely — but is
  slower, so we only run it when the initial retrieval looks uncertain.

The trigger logic (should_rerank):
  - If top_score is already high AND the top hit is clearly better than #2
    (large margin), retrieval is confident → skip reranker, save latency.
  - If top_score is low OR margin is small (several hits look equally good),
    retrieval is uncertain → run reranker to re-order.

Backend options (implement RerankerBackend protocol):
  - NoOpRerankerBackend  — passthrough, no reranking (good for development)
  - HTTPRerankerBackend  — calls an external reranker service (BGE, Cohere, etc.)
  - LocalRerankerBackend — runs a cross-encoder locally via sentence-transformers
"""
from __future__ import annotations

import copy
import logging
from dataclasses import replace, is_dataclass
from typing import List, Optional, Protocol, Sequence

from .models import DocumentHit, RerankConfig

log = logging.getLogger(__name__)


# ─── Backend protocol ─────────────────────────────────────────────────────────

class RerankerBackend(Protocol):
    def rerank(self, *, query: str, hits: Sequence[DocumentHit]) -> List[DocumentHit]:
        ...


class NoOpRerankerBackend:
    """Passthrough — returns hits unchanged. Use during development."""
    def rerank(self, *, query: str, hits: Sequence[DocumentHit]) -> List[DocumentHit]:
        return list(hits)


class HTTPRerankerBackend:
    """
    Calls an external HTTP reranker service.

    Expected API:
      POST /rerank
      Body: {"query": str, "hits": [{"id": str, "text": str}, ...]}
      Response: {"hits": [{"id": str, "score": float}, ...]}

    Replace the URL and request/response format to match your reranker.
    Options: BGE reranker, Cohere Rerank API, Jina Reranker, etc.
    """
    def __init__(self, base_url: Optional[str] = None):
        import os
        self._url = (base_url or os.getenv("RERANKER_URL", "http://localhost:8090")).rstrip("/")

    def rerank(self, *, query: str, hits: Sequence[DocumentHit]) -> List[DocumentHit]:
        import httpx

        payload = {
            "query": query,
            "hits": [{"id": h.doc_id, "text": h.text} for h in hits],
        }
        response = httpx.post(f"{self._url}/rerank", json=payload, timeout=10.0)
        response.raise_for_status()
        result = response.json()

        score_map = {r["id"]: float(r["score"]) for r in result.get("hits", [])}
        hits_list = list(hits)
        for h in hits_list:
            h.rerank_score = score_map.get(h.doc_id, 0.0)

        return sorted(hits_list, key=lambda h: h.rerank_score, reverse=True)


# ─── Trigger logic ────────────────────────────────────────────────────────────

def _base_score(h: DocumentHit) -> float:
    return max(h.dense_score, h.sparse_score, h.hybrid_score, h.rerank_score)


def should_rerank(hits: Sequence[DocumentHit], cfg: RerankConfig) -> bool:
    if not cfg.enabled or not hits:
        return False
    scores = sorted((_base_score(h) for h in hits), reverse=True)
    top = scores[0]
    margin = top - (scores[1] if len(scores) > 1 else 0.0)
    # Rerank only if retrieval is uncertain
    return top < cfg.min_top_score or margin < cfg.min_margin


# ─── Orchestrator ─────────────────────────────────────────────────────────────

def maybe_rerank(
    *,
    query: str,
    hits: Sequence[DocumentHit],
    cfg: RerankConfig,
    reranker: RerankerBackend,
) -> List[DocumentHit]:
    """
    Rerank hits if the trigger conditions are met. Falls back gracefully.

    Truncates chunk text before sending to reranker (max_doc_chars) so
    the reranker doesn't receive huge tokens — most rerankers cap input size.
    """
    hits_list = list(hits)
    if not should_rerank(hits_list, cfg):
        return hits_list

    candidates = hits_list[: cfg.candidates_k]

    # Truncate text for reranker without mutating originals
    def _truncate(h: DocumentHit) -> DocumentHit:
        if len(h.text) <= cfg.max_doc_chars:
            return h
        if is_dataclass(h):
            return replace(h, text=h.text[: cfg.max_doc_chars])
        hh = copy.copy(h)
        hh.text = h.text[: cfg.max_doc_chars]
        return hh

    candidates_trimmed = [_truncate(h) for h in candidates]

    try:
        reranked = reranker.rerank(query=query, hits=candidates_trimmed)
        if not reranked:
            log.warning("reranker returned empty — falling back to original order")
            return hits_list
    except Exception as exc:
        log.warning("reranker failed (%s) — falling back to original order", exc)
        return hits_list

    # Append any hits beyond candidates_k that weren't sent to the reranker
    merged = list(reranked) + hits_list[cfg.candidates_k :]
    if cfg.return_k is not None:
        merged = merged[: cfg.return_k]
    return merged
