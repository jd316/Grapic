"""Supabase client configuration and initialization."""

from supabase import create_client, Client

from app.config import SUPABASE_URL, SUPABASE_KEY, SUPABASE_SERVICE_KEY

# Public client (uses anon key - respects RLS)
_supabase_public: Client | None = None

# Service client (uses service role key - bypasses RLS for admin operations)
_supabase_service: Client | None = None


def get_supabase() -> Client:
    """Get the public Supabase client (respects RLS)."""
    global _supabase_public
    if _supabase_public is None:
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set in environment")
        _supabase_public = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _supabase_public


def get_supabase_service() -> Client:
    """Get the service Supabase client (bypasses RLS for admin operations)."""
    global _supabase_service
    if _supabase_service is None:
        if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in environment")
        _supabase_service = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    return _supabase_service


def verify_jwt(token: str) -> dict | None:
    """
    Verify a Supabase JWT token and return the user claims.
    Returns None if invalid.

    Uses Supabase's get_user endpoint to verify the token.
    This is secure because we rely on Supabase's API to validate the token,
    not just decode it locally. The JWT payload decode is only for extracting
    claims after Supabase has confirmed validity.
    """
    import requests
    import jwt
    import time
    from app.config import SUPABASE_URL, SUPABASE_SERVICE_KEY

    try:
        # Step 1: Verify token by calling Supabase's get_user endpoint
        # This ensures the token is valid and not revoked
        response = requests.get(
            f"{SUPABASE_URL}/auth/v1/user",
            headers={
                "Authorization": f"Bearer {token}",
                "apikey": SUPABASE_SERVICE_KEY,
            },
            timeout=5
        )

        if response.status_code != 200:
            return None

        # Step 2: Decode JWT payload (safe now that Supabase verified it)
        # We decode without signature verification for performance since
        # Supabase already validated it
        payload = jwt.decode(token, options={"verify_signature": False})

        # Step 3: Check expiration locally for extra safety
        if payload.get("exp", 0) < time.time():
            return None

        # Step 4: Verify issuer matches Supabase URL
        expected_issuer = f"{SUPABASE_URL}/auth/v1"
        if payload.get("iss") != expected_issuer:
            return None

        return payload

    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"JWT verification error: {e}")
        return None
