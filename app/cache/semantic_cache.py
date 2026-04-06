# app/cache/semantic_cache.py
from __future__ import annotations

import logging
from typing import Optional, Any
from langchain_core.messages import AIMessage, BaseMessage
from langchain_openai import OpenAIEmbeddings
from langchain_redis import RedisSemanticCache
from langchain_core.outputs import Generation
import os

logger = logging.getLogger("semantic_cache")


class QuerySemanticCache:
    """
    Semantic cache layer that sits before the agent node.
    Uses Redis to cache agent responses based on semantic similarity.
    """

    def __init__(
        self,
        redis_url: Optional[str] = None,
        distance_threshold: float = 0.15,  # Lower = stricter matching
        ttl: Optional[int] = 3600 * 24,  # 24 hours default
        embeddings: Optional[Any] = None,
    ):
        """
        Initialize the semantic cache.

        Args:
            redis_url: Redis connection URL (defaults to env var or localhost)
            distance_threshold: Max distance for cache hit (0.0-1.0, lower is stricter)
            ttl: Time-to-live for cache entries in seconds
            embeddings: Embedding model (defaults to OpenAI)
        """
        self.redis_url = redis_url or os.getenv(
            "REDIS_URL", "redis://localhost:6378"
        )
        self.distance_threshold = distance_threshold
        self.ttl = ttl

        # Initialize embeddings
        self.embeddings = embeddings or OpenAIEmbeddings()

        # Initialize Redis semantic cache
        self.cache = RedisSemanticCache(
            redis_url=self.redis_url,
            embeddings=self.embeddings,
            distance_threshold=self.distance_threshold,
            ttl=self.ttl,
            name="fintech_agent_cache",
            prefix="qa_cache:",
        )

        logger.info(
            "Semantic cache initialized redis_url=%s distance_threshold=%f ttl=%s",
            self.redis_url,
            self.distance_threshold,
            self.ttl,
        )

    def _create_cache_key(
        self, query: str, customer_id: Optional[str] = None
    ) -> str:
        """
        Create a cache key from query and optional customer_id.
        We include customer_id to ensure personalized responses aren't shared.
        """
        if customer_id:
            return f"{query}|customer:{customer_id}"
        return query

    def _create_llm_string(self) -> str:
        """Create a consistent LLM identifier string for cache lookups."""
        return "fintech_agent_v1"

    async def lookup(
        self, query: str, customer_id: Optional[str] = None
    ) -> Optional[str]:
        """
        Look up a cached response for the query.

        Args:
            query: User's query text
            customer_id: Optional customer ID for personalized caching

        Returns:
            Cached response text if found, None otherwise
        """
        try:
            cache_key = self._create_cache_key(query, customer_id)
            llm_string = self._create_llm_string()

            result = self.cache.lookup(cache_key, llm_string)

            if result:
                cached_text = result[0].text
                logger.info(
                    "Cache HIT query=%s customer_id=%s response_len=%d",
                    query[:50],
                    customer_id,
                    len(cached_text),
                )
                return cached_text

            logger.info(
                "Cache MISS query=%s customer_id=%s", query[:50], customer_id
            )
            return None

        except Exception as e:
            logger.error("Cache lookup failed error=%s", str(e), exc_info=True)
            return None

    async def store(
        self,
        query: str,
        response: str,
        customer_id: Optional[str] = None,
    ) -> bool:
        """
        Store a query-response pair in the cache.

        Args:
            query: User's query text
            response: Agent's response text
            customer_id: Optional customer ID for personalized caching

        Returns:
            True if stored successfully, False otherwise
        """
        try:
            cache_key = self._create_cache_key(query, customer_id)
            llm_string = self._create_llm_string()

            # Store as Generation object
            generation = Generation(text=response)
            self.cache.update(cache_key, llm_string, [generation])

            logger.info(
                "Cache STORE query=%s customer_id=%s response_len=%d",
                query[:50],
                customer_id,
                len(response),
            )
            return True

        except Exception as e:
            logger.error("Cache store failed error=%s", str(e), exc_info=True)
            return False

    async def clear(self) -> bool:
        """Clear all cache entries."""
        try:
            await self.cache.aclear()
            logger.info("Cache cleared successfully")
            return True
        except Exception as e:
            logger.error("Cache clear failed error=%s", str(e), exc_info=True)
            return False

    async def clear_for_customer(self, customer_id: str) -> bool:
        """
        Clear cache entries for a specific customer.
        Note: This requires manual implementation since RedisSemanticCache
        doesn't have built-in per-customer clearing.
        """
        # This would require custom Redis operations
        logger.warning(
            "Per-customer cache clearing not implemented customer_id=%s",
            customer_id,
        )
        return False