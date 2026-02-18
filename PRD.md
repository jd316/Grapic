# Product Requirements Document (PRD)

**Project Name:** Grapic
**Version:** 2.0
**Status:** Updated for Cross-Platform Frontend

---

## 1. Executive Summary

**Grapic** is a cross-platform event photo distribution platform designed to solve the logistical headache of sharing photos from large events. Instead of manually sorting through thousands of images or distributing massive zip files, organizers upload photos to a private space. Grapic uses facial recognition technology to automatically index faces. Attendees can then simply take a selfie on their mobile device or web browser to instantly retrieve all photos containing their face.

**Platform Support:**

- **iOS** (via Expo React Native)
- **Android** (via Expo React Native)
- **Web** (via Expo Router and React Native Web)
- All platforms share a single codebase with platform-specific optimizations

## 2. Problem Statement

- **For Organizers:** After an event (wedding, conference, hackathon), organizers are inundated with requests for photos. Uploading thousands of photos to a shared drive creates a chaotic user experience. Organizers need a cross-platform interface to manage events on-the-go.
- **For Attendees:** Attendees must manually scroll through thousands of high-resolution images to find themselves, often missing photos they were featured in. Mobile users need an intuitive, camera-first experience to quickly find and download their photos.

## 3. User Personas

- **The Organizer:** Needs a streamlined way to upload photos (bulk upload) and ensure attendees get their pictures without constant back-and-forth communication. Uses both web and mobile interfaces - creates events on desktop for convenience, manages and monitors events via mobile app on-site.
- **The Attendee:** Wants to find photos of themselves quickly without scrolling through a folder of 5,000 images. Values privacy, ease of access, and expects a seamless mobile-first experience. Prefers native camera integration and intuitive photo gallery views on their device.

## 4. Functional Requirements

### 4.1 Organizer Portal (Cross-Platform: Web, iOS, Android)

**Web Interface (Primary for setup):**

- **Event Creation:** Ability to create a new "Event Space" with a unique name and privacy settings.
- **Bulk Upload:** Support for uploading large batches of images (ZIP or multi-select) with progress indicators.
- **Access Control:** Ability to generate a unique Event ID or QR code to share with attendees.
- **Dashboard:** View analytics (e.g., number of photos processed, number of attendees who used the service).

**Mobile Interface (Management & Monitoring):**

- **Quick Event Overview:** View all active events with status indicators.
- **Real-time Monitoring:** Watch photo processing progress in real-time via SSE (Server-Sent Events).
- **QR Code Sharing:** Share event QR codes directly from mobile device using native sharing capabilities.
- **Basic Upload:** Upload individual photos or small batches from mobile camera/gallery when convenient.

### 4.2 Core Engine (Backend) - Unchanged

**Image Ingestion Pipeline:**

- Accept raw images from the upload service.
- **Pre-processing:** Resize/compress images for optimal storage and processing speed.
- **Face Detection & Encoding:** Detect faces in photos and generate unique facial embeddings (vectors).
- **Indexing:** Map facial embeddings to specific Photo IDs.
- **Selfie Matching Service:**
  - Accept a selfie image from an attendee.
  - Generate a facial embedding for the selfie.
  - **Vector Search:** Compare the selfie embedding against the database of stored face embeddings.
  - Return a list of Photo IDs where the similarity score exceeds a defined threshold (e.g., > 95%).

### 4.3 Attendee Portal (Cross-Platform: iOS, Android, Web)

**Universal Features (All Platforms):**

- **Event Join:** Input Event ID or scan QR code to enter the private space.
- **Camera Access:** Access device camera to capture a selfie using native camera APIs on mobile devices.
- **Photo Gallery:** Display a gallery of matched photos with responsive, platform-optimized layouts.
- **Download:** Allow individual photo downloads (or bulk download if zipping is feasible).

**Platform-Specific Features:**

**iOS/Android (Native):**

- **Camera Integration:** Use expo-camera for real-time selfie capture with live preview.
- **Photo Library Access:** Allow users to select photos from device camera roll as an alternative to live capture.
- **Native Sharing:** Share photos directly to other apps (social media, messages, email).
- **Push Notifications:** Notify users when photo processing is complete (optional feature).
- **Offline Cache:** Cache downloaded photos locally for offline viewing.

**Web:**

- **WebRTC Camera:** Access webcam for selfie capture on desktop browsers.
- **Drag & Drop Upload:** Alternative method to upload selfies on desktop.
- **Responsive Gallery:** Optimized grid layouts for various screen sizes.
- **Social Sharing:** Share photos via web URLs or platform-specific sharing APIs.

## 5. Non-Functional Requirements

### 5.1 Performance & Latency

- **Search Latency:** The selfie-to-results process must return photos in under 3 seconds.
- **Background Processing:** The initial indexing of event photos must happen asynchronously to prevent timeout errors during large uploads.
- **Mobile App Performance:** App launch time under 3 seconds, smooth 60fps animations, no jank during photo gallery scrolling.
- **Bundle Size:** Optimize Expo bundle size for fast downloads (<50MB initial bundle).

### 5.2 Cost Management (Critical Constraint)

- As noted in the source material, server costs and latency are primary concerns.
- **Optimization Strategy:** Use lightweight, open-source face recognition models (e.g., `face_recognition` Python library or MediaPipe) rather than expensive cloud APIs (like AWS Rekognition) to keep costs low/free.
- **Infrastructure:** Utilize object storage (e.g., AWS S3) for images and a vector database or efficient indexing system for embeddings.
- **Cross-Platform Efficiency:** Maximize code reuse across platforms using Expo's unified API. Platform-specific code should be minimal and only where necessary.

### 5.3 Privacy & Security

- **Data Retention:** Organizers must be able to set an expiration date for the event space (e.g., auto-delete after 7 days) to protect user privacy and save storage.
- **Access:** Event spaces must be private; users cannot browse photos without performing a face match.
- **Permissions:** Properly handle camera and photo library permissions on mobile platforms with clear user explanations.
- **Secure Communication:** All API communication must use HTTPS, with proper authentication (Supabase Auth).

### 5.4 User Experience (Cross-Platform)

- **Consistent Experience:** Core features should feel native on each platform while maintaining feature parity.
- **Platform Integration:** Use platform-specific UI patterns (iOS Human Interface Guidelines, Material Design for Android) where appropriate.
- **Responsive Design:** UI should adapt to different screen sizes and orientations gracefully.
- **Accessibility:** Support screen readers, dynamic text sizing, and other accessibility features across all platforms.

## 6. Technical Architecture & Implementation Strategy

The system follows an event-driven architecture to handle the high latency of image processing, with a unified cross-platform frontend.

### 6.1 High-Level Stack

| Layer | Technology |
|-------|------------|
| **Frontend** | **Expo SDK 52+** (React Native) |
| **Frontend Routing** | Expo Router (file-based routing with web support) |
| **Frontend State** | React Query (TanStack Query) for server state, Context/Zustand for local state |
| **UI Components** | React Native Paper or NativeBase for cross-platform components |
| **Backend API** | **Python FastAPI 0.128.8** (existing) |
| **Authentication** | **Supabase Auth** (existing) |
| **Queue** | Redis (existing) |
| **Worker** | Python environment running facial recognition (existing) |
| **Storage** | Object Storage (S3/Cloudflare R2) for raw images, Database (PostgreSQL) for metadata, Vector Store (pgvector) for face embeddings |

### 6.2 Architecture

```text
┌──────────────────────────────────────────────────────────────────┐
│                    Cross-Platform Frontend                       │
│                  (Expo React Native + Router)                    │
│                                                                  │
│  ┌──────────┐  ┌─────────┐  ┌──────────┐                         │
│  │    iOS   │  │ Android │  │   Web    │                         │
│  │   App    │  │   App   │  │   PWA    │                         │
│  └────┬─────┘  └───┬─────┘  └────┬─────┘                         │
│       │            │             │                               │
│       └────────────┴─────────────┘                               │
│                    │                                             │
│            ┌───────▼────────┐                                    │
│            │  Universal App │                                    │
│            │  (Single Code) │                                    │
│            └───────┬────────┘                                    │
└────────────────────┼─────────────────────────────────────────────┘
                     │ HTTPS / REST API
                     ▼
┌──────────────────────────────────────────────────┐
│         Your Server (VPS/Cloud)                  │
│                                                  │
│  ┌────────────┐  ┌───────────┐  ┌────────┐       │
│  │ PostgreSQL │  │   Redis   │  │ FastAPI│       │
│  │ + pgvector │  │  (queue)  │  │Backend │       │
│  └────────────┘  └───────────┘  └────────┘       │
│         │                              │         │
│         └──────────┬───────────────────┘         │
│                    │                             │
│         ┌──────────▼──────────┐                  │
│         │   Celery Workers    │                  │
│         └─────────────────────┘                  │
└──────────────────────────────────────────────────┘
                          │
                          ▼
              ┌─────────────────────┐
              │  Supabase Auth      │
              │  (External service) │
              │  - Sign up          │
              │  - Login            │
              │  - Password reset   │
              └─────────────────────┘
```

### 6.3 Key Expo Features & Integration

**Environment Configuration:**

- Use `EXPO_PUBLIC_API_URL` for backend API endpoint
- Environment variables managed via `.env` and EAS secrets
- Different configs for development, staging, and production

**API Integration:**

- React Query for efficient data fetching and caching
- FormData for multipart image uploads
- SSE (Server-Sent Events) for real-time progress tracking
- Supabase Auth client for authentication

**Camera & Media Handling:**

- `expo-camera` for native camera access on iOS/Android
- `expo-image-picker` for selecting from device photo library
- `expo-media-library` for saving photos to device
- Platform-agnostic component abstraction for web vs native

**Image Upload Flow:**

```
User takes selfie → Expo Camera captures image →
Resize/optimize client-side → FormData upload to FastAPI →
Backend processes → Return results → Display in gallery
```

**Platform-Specific Optimizations:**

**iOS:**

- Native camera UI with face detection overlay
- haptic feedback for better UX
- Share sheet integration
- Push notifications (via Expo Notifications)

**Android:**

- Material Design 3 components
- CameraX integration via expo-camera
- Android share intent
- Background processing support

**Web:**

- Responsive layouts using Tailwind Native or StyleSheet
- WebRTC for webcam access
- Progressive Web App (PWA) capabilities
- Keyboard navigation for accessibility

### 6.4 The "Hard Part" Pipeline (Detailed - Backend Unchanged)

1. **Upload:** Organizer uploads 1,000 photos via web or mobile app.
2. **Queueing:** The backend saves images to S3 and pushes 1,000 "process jobs" into the Redis Queue.
3. **Worker Processing (Background):**
    - Worker pulls a job.
    - Downloads image temporarily.
    - Runs face detection.
    - For every face found: Generate a 128d vector (embedding).
    - Save vector to DB: `{ vector: [...], photo_id: "img_123.jpg", face_location: [x,y,w,h] }`.
4. **User Search:**
    - User captures selfie on device (camera/webcam).
    - Client uploads selfie to backend.
    - Server generates vector for selfie (real-time).
    - Server queries Vector DB for nearest neighbors.
    - Server returns list of S3 URLs to frontend.
5. **Frontend Display:**
    - React Query caches results.
    - Gallery component displays photos with platform-optimized layouts.
    - Users can download or share individual photos.

### 6.5 Development & Deployment Workflow

**Local Development:**

```bash
# Frontend (Expo)
npm install
npx expo start --tunnel  # or --ios, --android, --web

# Backend (Existing)
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

**Build & Deploy:**

```bash
# iOS/Android via EAS Build
eas build --platform all

# Web deployment
npx expo export --platform web
eas deploy --platform web
```

**EAS Build Configuration (eas.json):**

- Development builds for testing
- Preview builds for beta testing
- Production builds for App Store/Play Store release

## 7. Platform-Specific Considerations

### 7.1 iOS

**Requirements:**

- macOS with Xcode for building
- Apple Developer account ($99/year) for App Store distribution
- Minimum iOS version: iOS 13+ (Expo SDK 52 target)

**Permissions:**

- NSCameraUsageDescription in Info.plist
- NSPhotoLibraryUsageDescription in Info.plist
- NSPhotoLibraryAddUsageDescription (for saving photos)

**Store Submission:**

- App Review guidelines compliance
- Privacy policy required
- App Store Connect setup

### 7.2 Android

**Requirements:**

- Minimum Android SDK: API 21+ (Android 5.0)
- Target Android SDK: API 34+ (Android 14)

**Permissions:**

- CAMERA in AndroidManifest.xml
- READ_EXTERNAL_STORAGE (Android < 13)
- READ_MEDIA_IMAGES (Android 13+)

**Distribution:**

- Google Play Store ($25 one-time fee)
- APK distribution for testing (side-loading)
- Privacy policy required

### 7.3 Web

**Requirements:**

- Modern browser with WebRTC support
- HTTPS required for camera access (except localhost)
- Responsive design for various screen sizes

**Limitations:**

- No push notifications (use service workers)
- Camera access requires HTTPS
- Download behavior varies by browser

### 7.4 Code Reuse Strategy

**Shared Code (90%+):**

- Business logic
- API clients
- State management
- Navigation structure
- Data fetching

**Platform-Specific Code (<10%):**

- Camera implementations
- File system access
- Native UI components
- Permission handling

**Pattern:**

```typescript
// Use Platform.OS for platform-specific code
import { Platform } from 'react-native';

const captureSelfie = async () => {
  if (Platform.OS === 'web') {
    // WebRTC camera implementation
    return captureWebcamImage();
  } else {
    // expo-camera for iOS/Android
    return captureNativeCameraImage();
  }
};
```

## 8. Success Metrics

- **User Engagement:** % of attendees who use the app to find photos.
- **Processing Efficiency:** Average time to process one photo in the background pipeline.
- **Accuracy:** False positive rate (showing a user someone else's photo) kept below 0.1%.
- **Cross-Platform Adoption:** Distribution of users across iOS, Android, and web platforms.
- **App Performance:** App crash rate < 1%, 4.8+ App Store rating, 4.5+ Play Store rating.
- **Mobile-Specific Metrics:** Average time from app launch to finding photos < 30 seconds.

## 9. Implementation Phases

### Phase 1: MVP (Months 1-3)

- Expo app with web and mobile support
- Basic camera/selfie capture
- Event join via QR code
- Photo gallery display
- Download functionality
- Native camera integration
- Photo library access
- Native sharing
- Push notifications
- Offline caching
- App Store and Play Store submission

### Phase 2: Advanced Features (Months 3-6)

- Advanced analytics dashboard
- Organizer mobile management features
- Bulk upload from mobile
- Enhanced UI with platform-specific polish
- Performance optimizations
- Social sharing integrations
