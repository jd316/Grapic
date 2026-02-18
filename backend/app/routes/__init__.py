"""Route modules."""

# Conditionally import auth when using Supabase
from app.config import USE_SUPABASE

if USE_SUPABASE:
    try:
        from . import auth  # noqa: F401
    except ImportError:
        pass  # Supabase not configured
