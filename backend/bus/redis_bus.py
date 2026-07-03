import json
from typing import Optional

import redis.asyncio as aioredis

from backend.config import settings


class RedisBus:
    def __init__(self, redis_client=None):
        self._redis = redis_client

    async def _get_redis(self):
        if self._redis is None:
            # Bounded pool (matches backend/core/events.py's sync client) — without
            # max_connections this defaults to unbounded, so a burst of concurrent
            # founders could open unlimited sockets against the single Redis
            # instance. redis.asyncio checks out a connection per in-flight call
            # (including brpop's blocking wait), so pooling also means push_task/
            # poll_results aren't stuck behind a blocking pop on the same socket.
            self._redis = aioredis.from_url(
                settings.redis_url,
                socket_connect_timeout=2, socket_timeout=30,
                health_check_interval=30, max_connections=64,
            )
        return self._redis

    def _task_queue_key(self, founder_id: str) -> str:
        return f"tasks:{founder_id}"

    def _result_queue_key(self, founder_id: str) -> str:
        return f"results:{founder_id}"

    async def push_task(self, founder_id: str, task_payload: dict):
        r = await self._get_redis()
        await r.lpush(self._task_queue_key(founder_id), json.dumps(task_payload))

    async def pop_task(self, founder_id: str, timeout: int = 5) -> Optional[dict]:
        r = await self._get_redis()
        result = await r.brpop(self._task_queue_key(founder_id), timeout=timeout)
        if result is None:
            return None
        _, value = result
        return json.loads(value)

    async def push_result(self, founder_id: str, result_payload: dict):
        r = await self._get_redis()
        await r.lpush(self._result_queue_key(founder_id), json.dumps(result_payload))

    async def poll_results(self, founder_id: str, max_results: int = 10) -> list[dict]:
        r = await self._get_redis()
        results = []
        for _ in range(max_results):
            value = await r.rpop(self._result_queue_key(founder_id))
            if value is None:
                break
            results.append(json.loads(value))
        return results


bus = RedisBus()
