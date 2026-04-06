"""
Vector search models — data classes for hits, filters, and config.

Replace field names in DocumentFilters with whatever metadata your chunks have.
Keep DocumentHit as-is — the retriever and reranker depend on its structure.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class DocumentHit:
    """A single retrieved document chunk."""
    doc_id: str
    text: str           # chunk content the LLM reads
    source: str         # document name / filename
    metadata: Optional[Dict[str, Any]] = None

    # Retrieval scores — set by the search functions, read by the reranker
    dense_score:  float = 0.0   # embedding similarity (cosine)
    sparse_score: float = 0.0   # keyword / BM25 score
    hybrid_score: float = 0.0   # weighted combination of dense + sparse
    rerank_score: float = 0.0   # set by reranker if used


@dataclass(frozen=True)
class DocumentFilters:
    """
    Optional metadata filters to narrow vector search.
    Add fields that match the metadata columns in your chunk table.

    Examples: language, document type, date range, department, category.
    """
    lang: Optional[str] = None       # e.g. "en", "ar"
    source: Optional[str] = None     # e.g. "faq.pdf", "policy_v2.pdf"
    tag: Optional[str] = None        # e.g. "refund", "billing"

    def to_cache_key(self) -> Tuple[Any, ...]:
        return (self.lang, self.source, self.tag)


@dataclass(frozen=True)
class VectorSearchConfig:
    """Tuning knobs for hybrid search."""
    dense_k: int = 25          # candidates from embedding search
    sparse_k: int = 25         # candidates from keyword search
    alpha: float = 0.5         # weight: alpha=dense, (1-alpha)=sparse
                               # 0.7 = prefer semantic, 0.3 = prefer keywords
    top_k: int = 8             # final results after merging


@dataclass(frozen=True)
class RerankConfig:
    """Controls when and how to rerank retrieved chunks."""
    enabled: bool = True

    # Trigger thresholds — rerank only when retrieval looks uncertain.
    # If the top hit is confident (high score, clear margin over #2),
    # skip reranking to save latency.
    min_top_score: float = 0.78
    min_margin: float = 0.08

    candidates_k: int = 20          # how many hits to send to reranker
    max_doc_chars: int = 1800       # truncate chunks before reranking
    return_k: Optional[int] = None  # if set, cap final result count
