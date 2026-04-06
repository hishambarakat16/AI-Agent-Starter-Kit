"""
Semantic Cache — Redis-backed response cache keyed by query meaning, not exact text.

How it fits into the agent:
  1. User sends a message
  2. LLM classifier decides: POLICY (knowledge-base Q&A) or PERSONALIZED (user-specific)
  3. If POLICY → embed the query → Redis vector search (cosine distance < threshold)
       Cache HIT  → return cached answer immediately, skip agent entirely
       Cache MISS → run agent → if knowledge-base tools were used → store in cache
  4. If PERSONALIZED → skip cache, always run agent

Why semantic (not exact-match) cache?
  "What is your return policy?" and "How do I return something?" are different
  strings but the same question. A semantic cache serves them the same answer.
  Exact-match caching (like Redis GET/SET) would miss these.

Configuration:
  REDIS_URL                          — Redis connection (default: redis://localhost:6379)
  SEMANTIC_CACHE_DISTANCE_THRESHOLD  — cosine distance threshold (default: 0.05)
                                       lower = stricter matching (fewer hits, more precise)
                                       higher = looser matching (more hits, risk of false positives)
  Cache TTL defaults to 24 hours.

Requires: Redis Stack (not plain Redis) — needs the vector search module.
  Docker: redis/redis-stack-server:latest
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

from langchain_core.outputs import Generation
from langchain_openai import OpenAIEmbeddings
from langchain_redis import RedisSemanticCache

logger = logging.getLogger("semantic_cache")


class QuerySemanticCache:
    """
    Wraps LangChain's RedisSemanticCache with async lookup/store helpers
    for use in the LangGraph agent graph nodes.

    Instantiated once in build_fintech_graph() and passed through AgentState.
    """

    def __init__(
        self,
        redis_url: Optional[str] = None,
        distance_threshold: float = 0.05,
        ttl: int = 3600 * 24,           # 24 hours
        embeddings: Optional[Any] = None,
        namespace: str = "agent_cache",  # change per project to avoid key collisions
    ):
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379")
        self.distance_threshold = distance_threshold
        self.ttl = ttl

        self.embeddings = embeddings or OpenAIEmbeddings()

        # RedisSemanticCache stores (query_embedding, response) pairs.
        # On lookup it embeds the incoming query and does a vector ANN search.
        # distance_threshold controls how similar two queries must be to count as a hit.
        self.cache = RedisSemanticCache(
            redis_url=self.redis_url,
            embeddings=self.embeddings,
            distance_threshold=self.distance_threshold,
            ttl=self.ttl,
            name=namespace,
            prefix="qa_cache:",
        )

        logger.info(
            "Semantic cache ready redis=%s threshold=%f ttl=%ds",
            self.redis_url, self.distance_threshold, self.ttl,
        )

    # ─── Cache key ────────────────────────────────────────────────────────────
    # Include user_id in the key when responses are user-specific (e.g. account
    # data). For pure knowledge-base answers (policy, FAQ), omit it so all users
    # share the same cache entry.

    def _key(self, query: str, user_id: Optional[str] = None) -> str:
        return f"{query}|user:{user_id}" if user_id else query

    def _llm_string(self) -> str:
        # LangChain uses this to namespace cache entries per model version.
        # Change it when your prompts or model change to invalidate old entries.
        return "agent_v1"

    # ─── Lookup ───────────────────────────────────────────────────────────────

    async def lookup(self, query: str, user_id: Optional[str] = None) -> Optional[str]:
        """
        Return a cached response if one exists within the distance threshold.
        Returns None on cache miss or any Redis error (fails open).
        """
        try:
            result = self.cache.lookup(self._key(query, user_id), self._llm_string())
            if result:
                text = result[0].text
                logger.info("cache HIT query=%s len=%d", query[:60], len(text))
                return text
            logger.info("cache MISS query=%s", query[:60])
            return None
        except Exception as exc:
            logger.error("cache lookup error: %s", exc)
            return None  # fail open — agent handles the request normally

    # ─── Store ────────────────────────────────────────────────────────────────

    async def store(self, query: str, response: str, user_id: Optional[str] = None) -> None:
        """
        Store a query-response pair. Call this after the agent responds,
        but only when the response came from knowledge-base tools (not
        personalized data) — otherwise you'd cache user-specific answers
        and serve them to other users.
        """
        try:
            self.cache.update(
                self._key(query, user_id),
                self._llm_string(),
                [Generation(text=response)],
            )
            logger.info("cache STORE query=%s len=%d", query[:60], len(response))
        except Exception as exc:
            logger.error("cache store error: %s", exc)

    # ─── Utilities ────────────────────────────────────────────────────────────

    async def clear(self) -> None:
        """Clear all cache entries (useful for testing or after content updates)."""
        try:
            await self.cache.aclear()
            logger.info("cache cleared")
        except Exception as exc:
            logger.error("cache clear error: %s", exc)
