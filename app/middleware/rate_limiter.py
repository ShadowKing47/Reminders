"""
Redis-backed rate limiting middleware.
Limits requests per IP using a simple fixed window counter.
"""
import time
from typing import Callable
from starlette.requests import Request
from starlette.responses import Response, PlainTextResponse


class RedisRateLimiter:
    def __init__(self, redis_client, limit: int = 60, window_seconds: int = 60):
        self.redis = redis_client
        self.limit = limit
        self.window = window_seconds

    async def __call__(self, request: Request, call_next: Callable):
        # Determine key by client IP
        client_ip = request.client.host if request.client else 'unknown'
        key = f"rl:{client_ip}"

        try:
            # Use INCR and EXPIRE to implement fixed-window
            current = self.redis.incr(key)
            if current == 1:
                self.redis.expire(key, self.window)
            if current > self.limit:
                retry_after = self.redis.ttl(key)
                return PlainTextResponse(
                    "Too Many Requests", status_code=429, headers={"Retry-After": str(retry_after)}
                )
        except Exception:
            # On Redis failure, allow request but do not enforce rate-limit
            return await call_next(request)

        response = await call_next(request)
        return response
