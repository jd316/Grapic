"""Security and rate limiting middleware."""

import time
import logging
from collections import defaultdict
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, JSONResponse

from app.config import USE_REDIS

logger = logging.getLogger(__name__)

_RATE_WINDOW = 60
_UPLOAD_LIMIT = 5
_MATCH_LIMIT = 10

# Fallback in-memory storage when Redis not available
_rate_store = defaultdict(list)

_redis_client = None


def _get_redis():
    """Get Redis client (lazy initialization)."""
    global _redis_client
    if _redis_client is None:
        if not USE_REDIS:
            return None
        try:
            import redis
            from app.config import REDIS_URL
            _redis_client = redis.from_url(REDIS_URL, decode_responses=True)
        except Exception as e:
            logger.error(f"Failed to connect to Redis for rate limiting: {e}")
            return None
    return _redis_client


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, enabled: bool = True):
        super().__init__(app)
        self.enabled = enabled

    async def dispatch(self, request: Request, call_next) -> Response:
        if not self.enabled:
            return await call_next(request)

        ip = _get_client_ip(request)
        path = request.url.path

        if path.endswith("/photos") and request.method == "POST":
            pattern = "upload"
            limit = _UPLOAD_LIMIT
        elif "/match" in path and "zip" not in path and request.method == "POST":
            pattern = "match"
            limit = _MATCH_LIMIT
        else:
            return await call_next(request)

        key = f"ratelimit:{ip}:{pattern}"
        now = time.time()

        # Try Redis first (for horizontal scalability)
        redis_client = _get_redis()
        if redis_client:
            try:
                # Use Redis pipeline for atomic operations
                pipe = redis_client.pipeline()
                pipe.zremrangebyscore(key, 0, now - _RATE_WINDOW)  # Remove old entries
                pipe.zcard(key)  # Count current entries
                results = pipe.execute()

                count = results[1]  # Get count from zcard

                if count >= limit:
                    return JSONResponse(
                        status_code=429,
                        content={"detail": "Rate limit exceeded. Try again later."},
                    )

                # Add current request
                redis_client.zadd(key, {str(now): now})
                redis_client.expire(key, _RATE_WINDOW)

                return await call_next(request)

            except Exception as e:
                logger.error(f"Redis rate limiting failed, falling back to in-memory: {e}")

        # Fallback to in-memory storage
        _rate_store[key] = [(ts, c) for ts, c in _rate_store[key] if now - ts < _RATE_WINDOW]
        count = sum(c for _, c in _rate_store[key])
        if count >= limit:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Try again later."},
            )
        _rate_store[key].append((now, 1))

        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        return response
