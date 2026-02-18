"""JWT verification middleware for Supabase Auth."""

import logging
from fastapi import Request, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from typing import Callable

from app.supabase_client import verify_jwt

logger = logging.getLogger(__name__)

# Paths that don't require authentication
PUBLIC_PATHS = {
    "/api/health",
    "/api/auth/magic-link",
    "/api/auth/verify",
    "/api/events/join",
    "/api/docs",
    "/api/openapi.json",
    "/api/redoc",
}


class SupabaseAuthMiddleware(BaseHTTPMiddleware):
    """
    Middleware to verify Supabase JWT tokens on protected endpoints.

    Public endpoints (login, signup, etc.) bypass authentication.
    Protected endpoints require Authorization: Bearer <token> header.

    On success, attaches user information to request.state.user
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path
        method = request.method

        # Skip auth for public paths
        if path in PUBLIC_PATHS or "/join" in path:
            return await call_next(request)

        # Check for Authorization header
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            # For public event access via access_code, we may allow without auth
            # But organizer operations require auth
            if self._requires_auth(path, method):
                return Response(
                    content='{"detail": "Missing authorization header"}',
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    media_type="application/json"
                )
            return await call_next(request)

        token = auth_header.split(" ")[1]

        # Verify JWT
        claims = verify_jwt(token)
        if not claims:
            return Response(
                content='{"detail": "Invalid or expired token"}',
                status_code=status.HTTP_401_UNAUTHORIZED,
                media_type="application/json"
            )

        # Attach user info to request state
        request.state.user_id = claims.get("sub")
        request.state.user_email = claims.get("email")
        request.state.user_claims = claims

        return await call_next(request)

    def _requires_auth(self, path: str, method: str) -> bool:
        """Check if a path requires authentication."""
        # POST /events - create event (requires auth)
        if path == "/api/events" and method == "POST":
            return True
        # PATCH/DELETE /events/{id} - update/delete event (requires auth)
        if "/api/events/" in path and method in ("PATCH", "DELETE"):
            return True
        # POST /events/{id}/photos - upload photos (requires auth)
        if "/photos" in path and method == "POST":
            return True
        # DELETE /photos/{id} - delete photo (requires auth)
        if "/photos/" in path and method == "DELETE":
            return True
        # POST /api/auth/anything except login/signup/reset-password
        if path.startswith("/api/auth/") and path not in PUBLIC_PATHS:
            return True

        return False


def get_user_id(request: Request) -> str | None:
    """Helper to get authenticated user ID from request state."""
    return getattr(request.state, "user_id", None)


def get_user_email(request: Request) -> str | None:
    """Helper to get authenticated user email from request state."""
    return getattr(request.state, "user_email", None)
