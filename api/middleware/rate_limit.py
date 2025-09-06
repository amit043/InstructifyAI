from __future__ import annotations

import time
from typing import Iterable

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

try:
    from redis import asyncio as aioredis  # type: ignore[import-not-found]
except Exception:  # pragma: no cover
    aioredis = None  # type: ignore[assignment]


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple fixed window rate limiter using Redis per-IP per-prefix.

    Not a perfect sliding window, but good enough for hot endpoints.
    """

    def __init__(
        self,
        app,
        *,
        redis_url: str,
        prefixes: Iterable[str] = ("/ingest", "/export"),
        max_requests: int = 60,
        window_seconds: int = 60,
    ) -> None:
        super().__init__(app)
        self.redis_url = redis_url
        self.prefixes = tuple(prefixes)
        self.max_requests = max_requests
        self.window = window_seconds
        self._redis = None

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        if not any(path.startswith(p) for p in self.prefixes):
            return await call_next(request)
        if aioredis is None:
            # Redis missing; allow request (fail-open)
            return await call_next(request)
        if self._redis is None:
            self._redis = aioredis.from_url(self.redis_url)  # type: ignore[call-arg]
        # Key by IP and coarse path prefix
        client_ip = request.headers.get("X-Forwarded-For", request.client.host if request.client else "unknown")
        prefix = next((p for p in self.prefixes if path.startswith(p)), self.prefixes[0])
        bucket = int(time.time() // self.window)
        key = f"ratelimit:{client_ip}:{prefix}:{bucket}"
        try:
            count = await self._redis.incr(key)  # type: ignore[union-attr]
            if count == 1:
                await self._redis.expire(key, self.window)
            if count > self.max_requests:
                return JSONResponse(status_code=429, content={"detail": "rate limit exceeded"})
        except Exception:  # pragma: no cover
            pass
        return await call_next(request)

