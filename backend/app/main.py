"""FastAPI application entry point."""

import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import CORS_ORIGINS, USE_SUPABASE, UPLOAD_DIR, SUPABASE_URL, SUPABASE_KEY, SUPABASE_SERVICE_KEY
from app.database import init_db, cleanup_expired_events
from app.services.worker import start_worker, stop_worker
from app.routes import events, photos, match, progress, analytics
from app.middleware import RateLimitMiddleware, SecurityHeadersMiddleware
from app.logging_config import setup_logging, RequestIdMiddleware
from app.metrics import setup_metrics_middleware, metrics_endpoint

# Import auth routes and middleware (REQUIRED)
from app.routes import auth
from app.auth_middleware import SupabaseAuthMiddleware

# Configure structured logging
setup_logging()
logger = logging.getLogger(__name__)


async def periodic_cleanup(interval_hours: int = 1):
    """Periodically clean up expired events."""
    while True:
        await asyncio.sleep(interval_hours * 3600)
        try:
            cleanup_expired_events()
        except Exception as e:
            logger.error(f"Cleanup error: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown."""
    logger.info("Starting Grapic server...")

    # Validate Supabase configuration (REQUIRED)
    if not SUPABASE_URL or not SUPABASE_KEY or not SUPABASE_SERVICE_KEY:
        raise RuntimeError(
            "SUPABASE_URL, SUPABASE_KEY, and SUPABASE_SERVICE_KEY must be set in environment. "
            "Authentication is required for all operations."
        )
    logger.info("Supabase authentication configured (REQUIRED)")

    init_db()
    start_worker()
    cleanup_expired_events()  # Clean on startup
    cleanup_task = asyncio.create_task(periodic_cleanup())
    logger.info("Grapic server ready")
    yield
    logger.info("Shutting down Grapic server...")
    cleanup_task.cancel()
    stop_worker()


app = FastAPI(
    title="Grapic",
    description="Event photo distribution platform with facial recognition",
    version="2.0.0",
    lifespan=lifespan,
)

# Request ID middleware (must be first to track all requests)
app.add_middleware(RequestIdMiddleware)

# Prometheus metrics middleware
setup_metrics_middleware(app)

# Supabase Auth middleware (REQUIRED for all operations)
app.add_middleware(SupabaseAuthMiddleware)
logger.info("Supabase authentication REQUIRED")

# Security headers (innermost = runs last on response)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware, enabled=True)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# Routes
app.include_router(auth.router)

app.include_router(events.router)
app.include_router(photos.router)
app.include_router(match.router)
app.include_router(progress.router)
app.include_router(analytics.router)

# Metrics endpoint
app.get("/metrics")(metrics_endpoint)


@app.get("/api/health")
def health_check():
    import shutil
    from app.config import USE_SELF_HOSTED_PG

    # Determine database type: self-hosted PG > Supabase > SQLite
    if USE_SELF_HOSTED_PG:
        db_type = "postgresql_self_hosted"
    elif USE_SUPABASE:
        db_type = "supabase"
    else:
        db_type = "sqlite"

    status = {"status": "ok", "service": "grapic", "database_type": db_type}

    # Check database connection
    if USE_SELF_HOSTED_PG:
        try:
            from app.database_postgres import get_pool
            pool = get_pool()
            conn = pool.getconn()
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.close()
            conn.close()
            status["database"] = "ok"
            # Add connection pool stats
            status["db_pool_size"] = pool.minconn + pool.maxconn
            status["db_pool_available"] = pool.pool.qsize() if hasattr(pool.pool, 'qsize') else "unknown"
        except Exception as e:
            status["database"] = "error"
            status["status"] = "degraded"
            status["database_error"] = str(e)
    elif USE_SUPABASE:
        try:
            from app.supabase_client import get_supabase
            supabase = get_supabase()
            # Simple query to test connection
            supabase.table("events").select("id").limit(1).execute()
            status["database"] = "ok"
        except Exception as e:
            status["database"] = "error"
            status["status"] = "degraded"
            status["database_error"] = str(e)
    else:
        try:
            from app.database import get_db
            with get_db() as conn:
                conn.execute("SELECT 1")
            status["database"] = "ok"
        except Exception as e:
            status["database"] = "error"
            status["status"] = "degraded"
            status["database_error"] = str(e)

    # Check disk space
    try:
        stat = shutil.disk_usage(str(UPLOAD_DIR))
        status["disk_free_gb"] = round(stat.free / (1024**3), 2)
    except Exception as e:
        status["disk"] = "error"
        status["disk_error"] = str(e)

    return status


if __name__ == "__main__":
    import uvicorn
    from app.config import HOST, PORT
    uvicorn.run("app.main:app", host=HOST, port=PORT, reload=True)
