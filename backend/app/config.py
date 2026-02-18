"""Application configuration."""

import os
from pathlib import Path

# Base directories
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
THUMBNAIL_DIR = DATA_DIR / "thumbnails"
DB_PATH = DATA_DIR / "grapic.db"

# Ensure directories exist
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
THUMBNAIL_DIR.mkdir(parents=True, exist_ok=True)

# Server
HOST = os.getenv("GRAPIC_HOST", "0.0.0.0")
PORT = int(os.getenv("GRAPIC_PORT", "8000"))

# Face recognition
SIMILARITY_THRESHOLD = float(os.getenv("GRAPIC_SIMILARITY_THRESHOLD", "0.40"))
# DeepFace Facenet cosine similarity: higher = more similar, 0.40+ is a good match

# Upload limits
MAX_FILE_SIZE_MB = int(os.getenv("GRAPIC_MAX_FILE_SIZE_MB", "20"))
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

# Thumbnail
THUMBNAIL_SIZE = (400, 400)

# Pre-processing (PRD 4.2)
MAX_IMAGE_DIMENSION = int(os.getenv("GRAPIC_MAX_IMAGE_DIMENSION", "2048"))
STORAGE_JPEG_QUALITY = int(os.getenv("GRAPIC_STORAGE_JPEG_QUALITY", "85"))

# Processing
MAX_WORKERS = int(os.getenv("GRAPIC_MAX_WORKERS", "4"))

# CORS (comma-separated origins, or "*" for all)
_cors = os.getenv("GRAPIC_CORS_ORIGINS", "*")
CORS_ORIGINS = ["*"] if _cors.strip() == "*" else [o.strip() for o in _cors.split(",") if o.strip()]

# Base URL for QR join links (e.g. your API or custom client)
BASE_URL = os.getenv("GRAPIC_BASE_URL", "http://localhost:8000")

# Monetization (PRD Section 7)
FREE_TIER_PHOTO_LIMIT = int(os.getenv("GRAPIC_FREE_TIER_LIMIT", "500"))

# Environment
ENV = os.getenv("GRAPIC_ENV", "development")

# Optional S3 (PRD 5.2)
USE_S3 = os.getenv("GRAPIC_S3_BUCKET") is not None
S3_BUCKET = os.getenv("GRAPIC_S3_BUCKET", "")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

# Supabase (Authentication - REQUIRED)
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")  # anon/public key
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")  # service_role key (bypasses RLS)

# Supabase must be configured for authentication
USE_SUPABASE = bool(SUPABASE_URL and SUPABASE_KEY and SUPABASE_SERVICE_KEY)

# Redis (for Celery queue and progress tracking)
USE_REDIS = os.getenv("REDIS_URL") is not None or os.getenv("GRAPIC_USE_REDIS", "").lower() == "true"
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Self-hosted PostgreSQL with pgvector
# When set, uses local PostgreSQL instead of Supabase for data storage
# Still uses Supabase for authentication (if SUPABASE_URL is also set)
USE_SELF_HOSTED_PG = os.getenv("DATABASE_URL") is not None or os.getenv("GRAPIC_USE_SELF_HOSTED_PG", "").lower() == "true"
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:password@localhost:5432/grapic")
