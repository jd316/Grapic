"""Structured logging configuration with request ID tracking."""

import logging
import json
import uuid
import time
from typing import Any, Dict
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

# Context variable for request ID (works across async tasks)
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="")


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Middleware to add request ID to all log entries."""

    async def dispatch(self, request: Request, call_next):
        # Generate or extract request ID
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request_id_ctx.set(request_id)

        # Add request ID to request state for access in endpoints
        request.state.request_id = request_id

        # Add X-Request-ID to response
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class StructuredFormatter(logging.Formatter):
    """JSON formatter for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        # Create log entry
        log_entry: Dict[str, Any] = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_ctx.get(""),
        }

        # Add exception info if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        # Add extra fields from record
        if hasattr(record, "extra_fields"):
            log_entry.update(record.extra_fields)

        return json.dumps(log_entry)


def setup_logging(level: str = "INFO"):
    """
    Setup structured logging for the application.

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    """
    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove default handlers
    root_logger.handlers.clear()

    # Console handler with structured formatter
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(StructuredFormatter())
    root_logger.addHandler(console_handler)

    # Configure specific loggers
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("fastapi").setLevel(logging.INFO)
    logging.getLogger("celery").setLevel(logging.INFO)
    logging.getLogger("deepface").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance with the given name."""
    return logging.getLogger(name)


def bind_logger(**kwargs) -> logging.LoggerAdapter:
    """
    Create a logger adapter with bound context fields.

    Usage:
        logger = bind_logger(user_id="123", event_id="456")
        logger.info("Processing photo")
    """
    logger = logging.getLogger(__name__)

    class LoggerAdapter(logging.LoggerAdapter):
        def process(self, msg, kwargs):
            extra = kwargs.get("extra", {})
            extra_fields = extra.pop("extra_fields", {})
            extra_fields.update(self.extra)
            extra["extra_fields"] = extra_fields
            kwargs["extra"] = extra
            return msg, kwargs

    return LoggerAdapter(logger, kwargs)
