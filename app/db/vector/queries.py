"""
Vector Search Queries — SQL patterns for pgvector.

Three search modes, each returning a list of DocumentHit:

  dense_search()   — embedding similarity (cosine distance via <=>)
  sparse_search()  — full-text keyword search (PostgreSQL FTS)
  hybrid_search()  — merge and score-fuse both

Use hybrid_search() by default — it handles both semantic questions
("what is the refund policy") and keyword lookups ("section 4.2").

Assumed table schema (adapt to yours):
  CREATE TABLE document_chunks (
      doc_id       TEXT PRIMARY KEY,
      text         TEXT,
      source       TEXT,
      lang         TEXT,
      tag          TEXT,
      metadata     JSONB,
      embedding    vector(1536),   -- OpenAI text-embedding-3-small
      fts_vector   tsvector        -- generated column or updated by trigger
  );
  CREATE INDEX ON document_chunks USING ivfflat (embedding vector_cosine_ops);
  CREATE INDEX ON document_chunks USING gin (fts_vector);

If you are NOT using pgvector, replace these functions with calls to your
vector DB client (Chroma, Pinecone, Weaviate, Qdrant, etc.) and keep the
same return type (List[DocumentHit]).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import psycopg2.extras

from .models import DocumentFilters, DocumentHit


# ─── Filter helper ────────────────────────────────────────────────────────────

def _build_where(filters: DocumentFilters) -> Tuple[str, Dict[str, Any]]:
    """Build a WHERE clause from a DocumentFilters, returning (sql, params)."""
    clauses: List[str] = []
    params: Dict[str, Any] = {}

    if filters.lang is not None:
        clauses.append("lang = %(lang)s")
        params["lang"] = filters.lang
    if filters.source is not None:
        clauses.append("source = %(source)s")
        params["source"] = filters.source
    if filters.tag is not None:
        clauses.append("tag = %(tag)s")
        params["tag"] = filters.tag

    where = " AND ".join(clauses) if clauses else "TRUE"
    return where, params


def _row_to_hit(r: Dict[str, Any]) -> DocumentHit:
    return DocumentHit(
        doc_id=r["doc_id"],
        text=r.get("text") or "",
        source=r.get("source") or "",
        metadata=r.get("metadata"),
    )


# ─── Dense search (embedding similarity) ─────────────────────────────────────

def dense_search(
    conn,
    *,
    query_vec: List[float],
    k: int,
    filters: Optional[DocumentFilters] = None,
    table: str = "document_chunks",
) -> List[DocumentHit]:
    """
    Vector similarity search using cosine distance (<=> operator).

    The score formula 1 / (1 + distance) maps cosine distance [0, 2] to
    a similarity-like score (1.0 = identical, approaching 0 = dissimilar).
    Using ORDER BY distance ASC + LIMIT is faster than computing scores
    in the WHERE clause — let the ivfflat index do the work.
    """
    filters = filters or DocumentFilters()
    where, params = _build_where(filters)
    params.update({"qvec": query_vec, "k": k})

    sql = f"""
    SELECT
        doc_id, text, source, metadata,
        (1.0 / (1.0 + (embedding <=> %(qvec)s::vector))) AS dense_score
    FROM {table}
    WHERE {where}
      AND embedding IS NOT NULL
    ORDER BY (embedding <=> %(qvec)s::vector) ASC
    LIMIT %(k)s
    """

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    hits = []
    for r in rows:
        h = _row_to_hit(r)
        h.dense_score = float(r.get("dense_score") or 0.0)
        hits.append(h)
    return hits


# ─── Sparse search (full-text keyword) ───────────────────────────────────────

def sparse_search(
    conn,
    *,
    query_text: str,
    k: int,
    filters: Optional[DocumentFilters] = None,
    table: str = "document_chunks",
    lang: Optional[str] = None,
) -> List[DocumentHit]:
    """
    Full-text search using PostgreSQL tsvector / tsquery.

    websearch_to_tsquery() is more robust than to_tsquery() — it handles
    natural language queries gracefully (no syntax errors on "what is the").
    ts_rank_cd uses cover density ranking which works well for longer docs.

    Use "simple" config for non-English text (Arabic, etc.) since language-
    specific stemming may not be available.
    """
    filters = filters or DocumentFilters()
    where, params = _build_where(filters)
    cfg = "simple" if (lang or filters.lang) == "ar" else "english"
    params.update({"q": query_text, "k": k, "cfg": cfg})

    sql = f"""
    WITH q AS (
        SELECT websearch_to_tsquery(%(cfg)s, %(q)s) AS tsq
    )
    SELECT
        doc_id, text, source, metadata,
        ts_rank_cd(fts_vector, q.tsq) AS sparse_score
    FROM {table}, q
    WHERE {where}
      AND q.tsq @@ fts_vector
    ORDER BY sparse_score DESC
    LIMIT %(k)s
    """

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    hits = []
    for r in rows:
        h = _row_to_hit(r)
        h.sparse_score = float(r.get("sparse_score") or 0.0)
        hits.append(h)
    return hits


# ─── Hybrid search (dense + sparse fusion) ────────────────────────────────────

def hybrid_search(
    conn,
    *,
    query_text: str,
    query_vec: List[float],
    top_k: int = 8,
    dense_k: int = 25,
    sparse_k: int = 25,
    alpha: float = 0.5,
    filters: Optional[DocumentFilters] = None,
    table: str = "document_chunks",
) -> List[DocumentHit]:
    """
    Hybrid search: run dense and sparse independently, merge by doc_id,
    min-max normalize each score, then fuse with alpha weighting.

    alpha=0.5  → equal weight to semantic and keyword
    alpha=0.7  → trust embeddings more (good for conceptual questions)
    alpha=0.3  → trust keywords more (good for exact term lookup)

    Min-max normalization is applied within each candidate set before
    fusion so scores from different search modes are on the same scale.
    """
    filters = filters or DocumentFilters()

    # Run both searches — candidate pools are intentionally larger than top_k
    d_hits = dense_search(conn, query_vec=query_vec, k=dense_k, filters=filters, table=table)
    s_hits = sparse_search(conn, query_text=query_text, k=sparse_k, filters=filters, table=table)

    # Min-max normalize dense scores
    d_scores = [h.dense_score for h in d_hits]
    d_norm = _minmax(d_scores)
    for h, s in zip(d_hits, d_norm):
        h.dense_score = s

    # Min-max normalize sparse scores
    s_scores = [h.sparse_score for h in s_hits]
    s_norm = _minmax(s_scores)
    for h, s in zip(s_hits, s_norm):
        h.sparse_score = s

    # Merge by doc_id
    merged: Dict[str, DocumentHit] = {}
    for h in d_hits:
        merged[h.doc_id] = h
    for h in s_hits:
        if h.doc_id in merged:
            merged[h.doc_id].sparse_score = h.sparse_score
        else:
            merged[h.doc_id] = h

    # Score fusion
    for h in merged.values():
        h.hybrid_score = (
            alpha * float(h.dense_score) +
            (1.0 - alpha) * float(h.sparse_score)
        )

    ranked = sorted(merged.values(), key=lambda h: h.hybrid_score, reverse=True)
    return ranked[:top_k]


def _minmax(values: List[float]) -> List[float]:
    if not values:
        return []
    vmin, vmax = min(values), max(values)
    if vmax == vmin:
        return [1.0] * len(values)
    return [(v - vmin) / (vmax - vmin) for v in values]
