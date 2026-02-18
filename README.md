# Grapic — Cross-Platform Event Photo Distribution Platform

Find your event photos instantly with a selfie. AI-powered facial recognition for weddings, conferences, and more. Works on iOS, Android, and Web from a single codebase.

---

## Quick Start

### Backend (Python FastAPI)

```bash
# 1. Clone and setup
git clone https://github.com/jd316/Grapic.git
cd grapic

# 2. Configure environment
cp .env.example .env
# Edit .env with your credentials:
#   - DATABASE_URL (your PostgreSQL)
#   - SUPABASE_URL, SUPABASE_KEY (for auth only)
#   - REDIS_URL (for Celery queue)

# 3. Start backend services
docker-compose up -d

# 4. API is ready at http://localhost:8000
# API docs: http://localhost:8000/docs
```

### Frontend (Expo Cross-Platform App)

```bash
# 1. Navigate to frontend (create if not exists)
mkdir -p frontend
cd frontend

# 2. Initialize Expo app (if starting from scratch)
npx create-expo-app@latest . --template blank-typescript

# 3. Install dependencies
npm install
npm install expo-camera expo-image-picker expo-media-library expo-sharing
npm install @tanstack/react-query axios
npm install react-native-paper react-native-safe-area-context

# 4. Configure environment variables
echo "EXPO_PUBLIC_API_URL=http://localhost:8000" > .env

# 5. Start development server
npx expo start

# 6. Run on specific platform:
#    - Press 'i' for iOS Simulator
#    - Press 'a' for Android Emulator
#    - Press 'w' for Web browser
#    - Scan QR code with Expo Go app for physical device
```

---

## Architecture

```mermaid
graph TD
    subgraph "Frontend - Expo Cross-Platform App"
        direction LR

        subgraph Platforms
            IOS["iOS App"]
            ANDROID["Android App"]
            WEB["Web PWA"]
        end

        subgraph Routing["Expo Router - File-Based Navigation"]
            EVENT_INDEX["event index page"]
            EVENT_CAMERA["camera page"]
            EVENT_GALLERY["gallery page"]
            ORG_INDEX["events list"]
            ORG_MANAGE["event manage page"]
        end

        subgraph API_Layer["React Query - State & Data Fetching"]
            USE_EVENTS["useEvents()"]
            USE_UPLOAD["useUploadPhotos()"]
            USE_MATCH["useMatchFace()"]
            USE_SSE["SSE real-time progress"]
        end

        subgraph Platform_Services["Platform-Specific Services"]
            EXPO_CAMERA["expo-camera<br/>iOS/Android"]
            EXPO_MEDIA["expo-media-library<br/>iOS/Android"]
            EXPO_SHARING["expo-sharing<br/>iOS/Android"]
            WEBRTC["WebRTC Camera<br/>Web"]
            PLATFORM["Platform.OS logic"]
        end

        IOS --> Routing
        ANDROID --> Routing
        WEB --> Routing

        Routing --> API_Layer
        API_Layer --> Platform_Services
    end

    subgraph "Backend Infrastructure"
        direction TB

        FASTAPI["Python FastAPI<br/>REST API Server"]

        subgraph Storage["Data Storage"]
            POSTGRES["PostgreSQL + pgvector<br/>Metadata & Embeddings"]
            S3["S3/Cloudflare R2<br/>Raw Images"]
        end

        subgraph Queue["Background Processing"]
            REDIS["Redis<br/>Message Broker"]
            CELERY["Celery Workers<br/>Face Recognition"]
        end

        FASTAPI <-->|Query Data| POSTGRES
        FASTAPI <-->|Store/Retrieve| S3
        FASTAPI <-->|Queue Jobs| REDIS
        REDIS <-->|Process Jobs| CELERY
        CELERY <-->|Store Embeddings| POSTGRES
        CELERY <-->|Process Images| S3
    end

    subgraph "External Services"
        SUPABASE["Supabase Auth<br/>Authentication Only"]
    end

    Platform_Services <-->|HTTPS / REST API| FASTAPI
    FASTAPI <-->|Authentication| SUPABASE

    classDef frontend fill:#e3f2fd,stroke:#1976d2,stroke-width:3px
    classDef backend fill:#f3e5f5,stroke:#7b1fa2,stroke-width:3px
    classDef external fill:#fff3e0,stroke:#f57c00,stroke-width:3px
    classDef storage fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
    classDef queue fill:#fff8e1,stroke:#fbc02d,stroke-width:2px

    class IOS,ANDROID,WEB,Routing,API_Layer,Platform_Services frontend
    class FASTAPI backend
    class POSTGRES,S3 storage
    class REDIS,CELERY queue
    class SUPABASE external
```

---

## Features

### Backend (Python FastAPI)

- ✅ **Facial Recognition** - DeepFace + Facenet, 128d embeddings
- ✅ **Vector Search** - pgvector for O(log n) similarity search
- ✅ **Background Processing** - Celery + Redis for scalability
- ✅ **Real-time Progress** - SSE streaming for upload/processing status
- ✅ **Authentication** - Supabase Auth (signup, login, password reset)
- ✅ **Analytics** - Event stats, processing metrics, system health
- ✅ **Data Retention** - Auto-expiring events with configurable TTL
- ✅ **Bulk Upload** - ZIP extraction + multi-file support
- ✅ **Access Control** - Unique access codes + organizer codes
- ✅ **QR Code Generation** - Easy attendee sharing

### Frontend (Expo Cross-Platform)

**Universal Features (All Platforms):**

- ✅ **Event Join** - Enter Event ID or scan QR code
- ✅ **Selfie Capture** - Camera access for face matching
- ✅ **Photo Gallery** - Responsive gallery of matched photos
- ✅ **Photo Download** - Save photos to device
- ✅ **Real-time Progress** - Live upload/processing updates

**Platform-Specific Features:**

**iOS/Android:**

- 📱 Native camera with live preview
- 📱 Photo library access for selfie selection
- 📱 Native sharing to other apps
- 📱 Push notifications (optional)
- 📱 Offline photo caching
- 📱 Haptic feedback

**Web:**

- 🌐 WebRTC webcam access
- 🌐 Drag & drop image upload
- 🌐 Responsive layouts
- 🌐 PWA support
- 🌐 Keyboard navigation

---

## Tech Stack

### Frontend

| Layer | Technology |
|-------|------------|
| **Framework** | Expo SDK 52+ (React Native) |
| **Routing** | Expo Router (file-based routing) |
| **State Management** | React Query (TanStack Query) + Zustand |
| **UI Components** | React Native Paper |
| **Camera & Media** | expo-camera, expo-image-picker, expo-media-library |
| **API Client** | Axios + React Query |
| **Styling** | StyleSheet / React Native Paper theme |
| **Build & Deploy** | EAS Build + EAS Hosting |

### Backend

| Layer | Technology |
|-------|------------|
| **Backend** | Python FastAPI 0.128.8 |
| **Authentication** | Supabase Auth |
| **Database** | PostgreSQL + pgvector (self-hosted) |
| **Face Recognition** | DeepFace (Facenet + OpenCV) |
| **Vector Search** | pgvector with IVFFlat index |
| **Task Queue** | Celery + Redis |
| **Progress Tracking** | Server-Sent Events (SSE) |
| **Image Storage** | Local filesystem or AWS S3 |

---

## Database Options

### Option 1: Self-Hosted PostgreSQL (Recommended) ⭐

**Production-ready configuration:**

- Full control over your data
- No database limits
- Fast vector search with pgvector
- Still uses Supabase for authentication (managed auth)

**Setup:**

```bash
# .env configuration
DATABASE_URL=postgresql://postgres:your_password@localhost:5432/grapic
USE_SELF_HOSTED_PG=true

# Supabase Auth (for authentication only)
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-anon-key
SUPABASE_SERVICE_KEY=your-service-role-key
```

### Option 2: Supabase (Both Auth + Database)

- Fully managed database
- No server maintenance
- RLS policies included
- Free tier available

**Setup:**

```bash
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-anon-key
SUPABASE_SERVICE_KEY=your-service-role-key
```

### Option 3: SQLite (Development)

- No authentication (single-organizer mode)
- Local file-based database
- Simple setup for testing

**Setup:**

- Leave all Supabase vars unset
- Automatically falls back to SQLite

---

## Docker Services

```yaml
services:
  postgres:      # PostgreSQL + pgvector
  backend:       # FastAPI web server
  redis:         # Celery message broker
  celery_worker: # Background task processors
```

All services run on **YOUR infrastructure** - no external dependencies (except optional Supabase Auth).

**Frontend runs separately** via Expo development server or production builds.

---

## API Endpoints

### Authentication (Supabase)

| Method | Endpoint | Auth Required |
|--------|----------|---------------|
| POST | `/api/auth/signup` | No |
| POST | `/api/auth/login` | No |
| POST | `/api/auth/logout` | Yes |
| POST | `/api/auth/refresh` | No |
| GET | `/api/auth/me` | Yes |

### Events

| Method | Endpoint | Auth Required (Supabase) |
|--------|----------|-------------------------------|
| POST | `/api/events` | Yes (for organizer events) |
| GET | `/api/events` | Yes (list user's events) |
| GET | `/api/events/{id}` | No |
| PATCH | `/api/events/{id}` | Yes (owner only) |
| DELETE | `/api/events/{id}` | Yes (owner only) |
| GET | `/api/events/{id}/qr` | No |
| POST | `/api/events/join` | No (uses access_code) |
| POST | `/api/events/organizer-join` | No (uses organizer_code) |

### Photos

| Method | Endpoint | Auth Required |
|--------|----------|---------------|
| POST | `/api/events/{id}/photos` | Yes (owner only) |
| GET | `/api/events/{id}/photos` | No |
| GET | `/api/photos/{id}/image` | No |
| GET | `/api/photos/{id}/download` | No |
| DELETE | `/api/photos/{id}` | Yes (owner only) |

### Face Matching

| Method | Endpoint | Auth Required |
|--------|----------|---------------|
| POST | `/api/events/{id}/match` | No |
| GET | `/api/events/{id}/match/zip` | No |

### Progress & Analytics

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/events/{id}/progress` | SSE stream for real-time upload/processing progress |
| GET | `/api/events/{id}/progress/status` | Polling endpoint for progress |
| GET | `/api/analytics/events/{id}/stats` | Event analytics |
| GET | `/api/analytics/system/health` | System health check |
| POST | `/api/analytics/events/{id}/retry-failed` | Retry failed photos (Celery only) |

### System

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/health` | Health check (DB + disk status) |

---

## Environment Variables

### Backend (.env)

Copy `.env.example` to `.env` and configure:

```bash
# ─── Server ──────────────────────────────────────
GRAPIC_HOST=0.0.0.0
GRAPIC_PORT=8000

# ─── Face Recognition ────────────────────────────
GRAPIC_SIMILARITY_THRESHOLD=0.40

# ─── Self-Hosted PostgreSQL ────────────────────────
DATABASE_URL=postgresql://postgres:your_password@localhost:5432/grapic
USE_SELF_HOSTED_PG=true

# ─── Supabase Auth (Authentication ONLY) ───────────
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-anon-key
SUPABASE_SERVICE_KEY=your-service-role-key

# ─── Redis (Celery Queue) ──────────────────────────
REDIS_URL=redis://localhost:6379/0

# ─── Image Storage ────────────────────────────────
# GRAPIC_S3_BUCKET=your-bucket  # Optional: use S3 instead of local
# AWS_ACCESS_KEY_ID=...
# AWS_SECRET_ACCESS_KEY=...

# ─── Other ───────────────────────────────────────
GRAPIC_MAX_FILE_SIZE_MB=20
GRAPIC_FREE_TIER_LIMIT=500
```

### Frontend (frontend/.env)

```bash
# API endpoint for backend
EXPO_PUBLIC_API_URL=http://localhost:8000

# Optional: Supabase client config
# EXPO_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
# EXPO_PUBLIC_SUPABASE_ANON_KEY=your-anon-key
```

---

## Installation

### Backend Dependencies

```bash
pip install -r backend/requirements.txt
```

### Frontend Dependencies

```bash
cd frontend
npm install

# Expo SDK
npm install expo-camera expo-image-picker expo-media-library expo-sharing
npm install expo-constants expo-status-bar

# API & State
npm install @tanstack/react-query axios

# UI Components
npm install react-native-paper react-native-safe-area-context
npm install @react-navigation/native @react-navigation/native-stack
```

### Database Initialization

**For Self-Hosted PostgreSQL:**

- Database auto-initializes on first run
- Tables, indexes, and functions created automatically

**For Supabase:**

- Run migration in Supabase SQL Editor: `backend/supabase/migrations/001_initial_schema.sql`

---

## Running the Application

### Backend Development

```bash
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Backend Production (Docker)

```bash
docker-compose up -d
```

**Services:**

- Backend: `http://localhost:8000`
- API docs: `http://localhost:8000/docs`
- PostgreSQL: `localhost:5432`
- Redis: `localhost:6379`

### Frontend Development

```bash
cd frontend
npx expo start
```

**Options:**

- Press `i` - Open in iOS Simulator
- Press `a` - Open in Android Emulator
- Press `w` - Open in web browser
- Scan QR code - Use Expo Go on physical device

### Frontend Production Builds

```bash
# Build for all platforms
eas build --platform all

# Build for specific platform
eas build --platform ios
eas build --platform android

# Export web build
npx expo export --platform web
```

---

## Performance

| Metric | Value |
|--------|-------|
| Vector search (1k faces) | ~5ms |
| Vector search (100k faces) | ~30ms |
| Photo processing avg | ~1.2s |
| Search latency target | < 3s |
| App launch time | < 3s |
| Initial bundle size | < 50MB |

---

## Security Considerations

### Production Checklist

Backend:

- [ ] Change default PostgreSQL password in `docker-compose.yml`
- [ ] Set strong `GRAPIC_SIMILARITY_THRESHOLD` (0.40-0.60 recommended)
- [ ] Configure `GRAPIC_CORS_ORIGINS` to your frontend domain
- [ ] Use HTTPS in production
- [ ] Set up database backups
- [ ] Configure firewall rules
- [ ] Monitor system health via `/api/analytics/system/health`

Frontend:

- [ ] Configure proper CORS for API communication
- [ ] Set up SSL/TLS for production deployments
- [ ] Implement proper permission handling for camera and photo access
- [ ] Secure sensitive data with environment variables
- [ ] Test on physical devices before store submission

### Rate Limiting

Enabled by default on backend:

- Upload: 5 requests per minute
- Match: 10 requests per minute

---

## Platform-Specific Setup

### iOS

**Requirements:**

- macOS with Xcode 15+
- CocoaPods installed
- Apple Developer account for App Store distribution

**Permissions in app.json:**

```json
{
  "expo": {
    "ios": {
      "infoPlist": {
        "NSCameraUsageDescription": "Allow access to camera to take selfie for photo matching",
        "NSPhotoLibraryUsageDescription": "Allow access to photo library to select selfie",
        "NSPhotoLibraryAddUsageDescription": "Allow saving photos to device"
      }
    }
  }
}
```

### Android

**Permissions in app.json:**

```json
{
  "expo": {
    "android": {
      "permissions": [
        "CAMERA",
        "READ_EXTERNAL_STORAGE",
        "READ_MEDIA_IMAGES",
        "WRITE_EXTERNAL_STORAGE"
      ]
    }
  }
}
```

### Web

**Requirements:**

- Modern browser with WebRTC support
- HTTPS required for camera access (except localhost)
- Progressive Web App (PWA) capabilities

---

## Troubleshooting

### Backend

#### Database connection errors

```
# Check PostgreSQL is running
docker-compose logs postgres

# Check connection string
echo $DATABASE_URL
```

#### Authentication errors

```
# Verify Supabase credentials
echo $SUPABASE_URL
echo $SUPABASE_KEY
```

#### Vector search not working

```
# Check pgvector is enabled
docker exec -it grapic-postgres-1 psql -U postgres -d grapic -c "SELECT extversion FROM pg_extension WHERE extname = 'vector';"
```

### Frontend

#### Camera not working

```
# Check permissions are configured in app.json
# For iOS: Verify NSCameraUsageDescription
# For Android: Verify CAMERA permission
# For Web: Ensure using HTTPS (except localhost)
```

#### API connection issues

```
# Verify EXPO_PUBLIC_API_URL is set correctly
# For physical devices: Use your machine's IP address instead of localhost
# Example: EXPO_PUBLIC_API_URL=http://192.168.1.100:8000
```

#### Build errors

```
# Clear Expo cache
npx expo start -c

# Reinstall dependencies
rm -rf node_modules package-lock.json
npm install

# Check Expo doctor
npx expo doctor
```

---

## Testing

### Backend Tests

```bash
# Install test dependencies
pip install -r backend/requirements.txt

# Run tests
cd backend
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=app --cov-report=html
```

### Frontend Tests

```bash
cd frontend

# Run Jest tests
npm test

# Run with coverage
npm test -- --coverage
```

---

## Monitoring

### Backend Health Check

```bash
curl http://localhost:8000/api/health
```

### Prometheus Metrics

```bash
curl http://localhost:8000/metrics
```

Key metrics:

- `grapic_http_requests_total` - Total HTTP requests
- `grapic_http_request_duration_seconds` - Request latency
- `grapic_photos_processed_total` - Photos processed
- `grapic_events_active` - Active events

---

## Deployment

See **[DEPLOYMENT.md](DEPLOYMENT.md)** for complete production deployment guide including:

- Backend environment configuration
- Database setup
- Redis configuration
- Supabase Auth setup
- Cloud deployment (AWS, GCP, DigitalOcean)
- Frontend deployment (EAS Build, App Store, Play Store)
- Monitoring & maintenance
- Backup & restore procedures
- Security checklist

---

## Production Features

### Backend Scalability

- ✅ Redis-based progress tracking (horizontal scaling)
- ✅ Redis-based rate limiting (distributed)
- ✅ Celery workers for background processing
- ✅ Connection pooling for database

### Backend Reliability

- ✅ Automatic retry for failed photo processing
- ✅ Scheduled cleanup of expired events
- ✅ Database backup script included
- ✅ Structured JSON logging with request tracking

### Backend Observability

- ✅ Prometheus metrics export
- ✅ Structured logging with request IDs
- ✅ Health check endpoint with pool monitoring
- ✅ Real-time progress via SSE

### Frontend Performance

- ✅ Code splitting and lazy loading
- ✅ Image optimization and caching
- ✅ Platform-specific optimizations
- ✅ Fast refresh for development
- ✅ Production bundle optimization

---

## Documentation

- **PRD:** See [PRD.md](PRD.md) for detailed product requirements
- **Deployment Guide:** See [DEPLOYMENT.md](DEPLOYMENT.md) for production deployment
- **Supabase Setup:** See `backend/supabase/README.md` for Supabase configuration
- **Issues:** [GitHub Issues](https://github.com/your-repo/issues)

---

## License

MIT License - see [LICENSE](LICENSE) file for details.
