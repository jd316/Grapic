"""Pydantic models for API request/response schemas."""

from pydantic import BaseModel, Field, EmailStr, ConfigDict
from typing import Optional
from datetime import datetime


# ─── Events ─────────────────────────────────────────────────────────

class EventCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)
    expires_in_days: Optional[int] = Field(default=7, ge=1, le=90)
    # Optional branding fields
    branding_logo_url: Optional[str] = Field(None, max_length=500)
    branding_company_name: Optional[str] = Field(None, max_length=200)
    branding_custom_css: Optional[str] = Field(None, max_length=5000)


class EventResponse(BaseModel):
    model_config = ConfigDict(json_encoders={datetime: lambda v: v.isoformat() if v else None})

    id: str
    user_id: Optional[str] = None
    name: str
    description: str
    created_at: datetime
    expires_at: Optional[datetime]
    access_code: str
    organizer_code: Optional[str] = None
    photo_count: int
    processed_count: int
    attendee_count: int
    avg_processing_sec: Optional[float] = None
    engagement_pct: Optional[float] = None


class EventUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=1000)
    expires_in_days: Optional[int] = Field(None, ge=1, le=90)


class EventJoin(BaseModel):
    access_code: str = Field(..., min_length=1, max_length=20)


class OrganizerJoin(BaseModel):
    organizer_code: str = Field(..., min_length=1, max_length=20)


# ─── Photos ─────────────────────────────────────────────────────────

class PhotoResponse(BaseModel):
    id: str
    event_id: str
    filename: str
    original_name: str
    file_size: int = 0
    width: int = 0
    height: int = 0
    face_count: int = 0
    status: str
    uploaded_at: str
    processed_at: Optional[str] = None


class UploadResponse(BaseModel):
    uploaded: int
    photos: list[PhotoResponse]


# ─── Match ──────────────────────────────────────────────────────────

class MatchResult(BaseModel):
    photo_id: str
    filename: str
    original_name: str
    similarity: float
    thumbnail_url: str
    download_url: str


class MatchResponse(BaseModel):
    matched_count: int
    results: list[MatchResult]


# ─── General ────────────────────────────────────────────────────────

class StatusResponse(BaseModel):
    status: str
    message: str = ""


# ─── Authentication ────────────────────────────────────────────────────

class SignUpRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=100)
    full_name: Optional[str] = Field(None, max_length=200)


class SignUpResponse(BaseModel):
    message: str
    user_id: Optional[str] = None
    email: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    user: "UserResponse"


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class RefreshTokenResponse(BaseModel):
    access_token: str


class ResetPasswordRequest(BaseModel):
    email: EmailStr


class UpdatePasswordRequest(BaseModel):
    password: str = Field(..., min_length=8, max_length=100)


class UserProfile(BaseModel):
    id: str
    email: str
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    subscription_tier: str = "free"


class UserResponse(BaseModel):
    id: str
    email: str
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    subscription_tier: str = "free"


class UpdateProfileRequest(BaseModel):
    full_name: Optional[str] = Field(None, max_length=200)
    avatar_url: Optional[str] = None
