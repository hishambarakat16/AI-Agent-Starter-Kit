# Semantic Cache Guide

The semantic cache sits between the user's message and the agent. For knowledge-base questions (FAQs, policy, documentation), it can return a cached answer instantly — no LLM call, no tool calls, no latency.

---

## How It Works

```
User message
     │
     ▼
LLM classifier (gpt-4o-mini, ~100ms)
     │
     ├── PERSONALIZED  →  skip cache, go straight to agent
     │   (e.g. "what's my balance?", "show my transactions")
     │
     └── POLICY        →  embed query → Redis vector search
                               │
                               ├── HIT (distance < threshold)
                               │    └── return cached answer immediately
                               │
                               └── MISS
                                    └── run agent
                                         │
                                         └── if knowledge-base tools were used
                                              → store response in cache
```

The key distinction: **personalized queries always hit the agent** — you never want to cache "what's my balance?" and return it to a different user. Only knowledge-base answers (same for everyone) get cached.

---

## Why Semantic (Not Exact-Match)?

These are three different strings but the same question:
- "What is your return policy?"
- "How do I return something?"
- "What's the refund process?"

A semantic cache embeds each query and finds matches by meaning (cosine similarity), so all three hit the same cached answer. A traditional key-value cache (`redis GET/SET`) would miss all three.

---

## Configuration

| Variable | Default | Description |
|---|---|---|
| `REDIS_URL` | `redis://localhost:6378` | Redis connection URL |
| `SEMANTIC_CACHE_DISTANCE_THRESHOLD` | `0.05` | Cosine distance threshold for a cache hit |

**Tuning the threshold:**
- `0.05` — strict. Only very close paraphrases match. Fewer false positives, fewer hits.
- `0.15` — loose. More cache hits, but risk of serving a slightly wrong cached answer.
- Start at `0.05` and increase if you want more aggressive caching.

**Cache TTL:** 24 hours. Entries expire automatically. After a content update (new policy docs, updated FAQs), clear the cache so stale answers aren't served — see below.

---

## Redis Stack Requirement

The semantic cache uses Redis's vector search module (`RedisSearch`) to do cosine similarity lookups. This module is only available in **Redis Stack** — not in plain Redis.

```yaml
# docker-compose.yml — correct
image: redis/redis-stack-server:latest

# WRONG — will boot fine but crash at runtime when the cache initialises
image: redis:alpine
```

The `docker-compose.yml` already uses `redis-stack-server`. If you're running Redis locally for development, install [Redis Stack](https://redis.io/docs/stack/), not plain Redis.

---

## Port Mapping

```
Host port 6378  →  Container port 6379
```

Port `6378` is used on the host to avoid conflicts with a local Redis instance you might already be running on `6379`. Inside the Docker network, services always connect to `redis:6379`.

```bash
# .env for local dev (outside Docker)
REDIS_URL=redis://localhost:6378

# Overridden automatically inside Docker
REDIS_URL=redis://redis:6379
```

---

## Clearing the Cache

After updating your knowledge base content, clear old cached answers:

```bash
# Clear all cache entries
docker exec agent-redis redis-cli KEYS "qa_cache:*" | xargs docker exec -i agent-redis redis-cli DEL

# Or from inside the container
docker exec -it agent-redis redis-cli
> KEYS qa_cache:*
> DEL qa_cache:key1 qa_cache:key2 ...
```

---

## Relevant Files

| File | What it does |
|---|---|
| `app/cache/semantic_cache.py` | `QuerySemanticCache` — lookup, store, clear |
| `app/graphs/fintech_graph.py` | `semantic_cache_lookup` and `cache_response` nodes in the agent graph |
| `docker/docker-compose.yml` | Redis Stack service config with memory limits and persistence |
