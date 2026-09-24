from functools import lru_cache

import redis

from .config import settings


@lru_cache(maxsize=1)
def get_client() -> redis.Redis:
    """Return a process-wide Redis client with string decoding enabled."""
    return redis.Redis.from_url(settings.redis_url, decode_responses=True)
