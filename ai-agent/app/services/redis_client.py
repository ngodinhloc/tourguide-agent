from typing import Optional
import redis.asyncio as aioredis
from app.configs.settings import settings


class RedisClient:
    def __init__(self):
        self._client: Optional[aioredis.Redis] = None

    def get(self) -> aioredis.Redis:
        if self._client is None:
            self._client = aioredis.from_url(settings.redis_url, decode_responses=True)
        return self._client
