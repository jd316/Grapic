"""Prometheus metrics export for Grapic."""

import time
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from fastapi import Response
from typing import Callable
from functools import wraps

# ============================================================================
# METRICS DEFINITIONS
# ============================================================================

# HTTP metrics
http_requests_total = Counter(
    "grapic_http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"]
)

http_request_duration_seconds = Histogram(
    "grapic_http_request_duration_seconds",
    "HTTP request latency",
    ["method", "endpoint"]
)

# Photo processing metrics
photos_processed_total = Counter(
    "grapic_photos_processed_total",
    "Total photos processed",
    ["status"]  # success, error
)

photos_processing_duration_seconds = Histogram(
    "grapic_photos_processing_duration_seconds",
    "Photo processing latency",
    ["event_id"]
)

faces_detected_total = Counter(
    "grapic_faces_detected_total",
    "Total faces detected",
    ["event_id"]
)

# Event metrics
events_created_total = Counter(
    "grapic_events_created_total",
    "Total events created"
)

events_active = Gauge(
    "grapic_events_active",
    "Currently active events"
)

# Match operations
match_requests_total = Counter(
    "grapic_match_requests_total",
    "Total match requests",
    ["status"]
)

match_duration_seconds = Histogram(
    "grapic_match_duration_seconds",
    "Match operation latency"
)

# Database metrics
db_connections_active = Gauge(
    "grapic_db_connections_active",
    "Active database connections"
)

db_query_duration_seconds = Histogram(
    "grapic_db_query_duration_seconds",
    "Database query latency",
    ["query_type"]
)

# Storage metrics
storage_bytes_used = Gauge(
    "grapic_storage_bytes_used",
    "Storage space used in bytes"
)


# ============================================================================
# MIDDLEWARE
# ============================================================================

def track_http_endpoint(func: Callable):
    """Decorator to track HTTP endpoint metrics."""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        start_time = time.time()
        try:
            result = await func(*args, **kwargs)
            status = "success"
            return result
        except Exception as e:
            status = "error"
            raise e
        finally:
            duration = time.time() - start_time
            # Extract endpoint info from args if available
            endpoint = "unknown"
            method = "unknown"

            http_requests_total.labels(
                method=method,
                endpoint=endpoint,
                status=status
            ).inc()
            http_request_duration_seconds.labels(
                method=method,
                endpoint=endpoint
            ).observe(duration)

    return wrapper


# ============================================================================
# FASTAPI INTEGRATION
# ============================================================================

async def metrics_endpoint():
    """Prometheus metrics endpoint."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


def setup_metrics_middleware(app):
    """Setup Prometheus metrics middleware for FastAPI."""
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request

    class PrometheusMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            start_time = time.time()
            method = request.method
            path = request.url.path

            # Process request
            response = await call_next(request)

            # Record metrics
            duration = time.time() - start_time
            status = response.status_code

            http_requests_total.labels(
                method=method,
                endpoint=path,
                status=str(status)
            ).inc()

            http_request_duration_seconds.labels(
                method=method,
                endpoint=path
            ).observe(duration)

            return response

    app.add_middleware(PrometheusMiddleware)
