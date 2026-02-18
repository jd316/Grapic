"""Authentication routes using Supabase Magic Links (Passwordless)."""

import logging
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, EmailStr
from typing import Optional

from app.supabase_client import get_supabase
from app.config import USE_SELF_HOSTED_PG

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ─── Models ─────────────────────────────────────────────────────────────────


class MagicLinkRequest(BaseModel):
    """Request to send a magic link email."""
    email: EmailStr
    full_name: Optional[str] = None


class MagicLinkResponse(BaseModel):
    """Response after sending magic link."""
    message: str
    email: str


class VerifyTokenRequest(BaseModel):
    """Verify magic link token and get session."""
    access_token: str
    refresh_token: str


class UserProfile(BaseModel):
    """User profile response."""
    id: str
    email: str
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    subscription_tier: str = "free"


# ─── Routes ────────────────────────────────────────────────────────────────


@router.post("/magic-link", response_model=MagicLinkResponse)
async def send_magic_link(data: MagicLinkRequest, request: Request):
    """
    Send a magic link to the user's email for passwordless authentication.

    If the user doesn't exist, they will be created automatically.
    The magic link contains a token that logs them in when clicked.
    """
    try:
        supabase = get_supabase()

        # Supabase handles both new and existing users with magic links
        # The redirectTo URL should point to your frontend where the token is captured
        redirect_url = str(request.headers.get("Origin", "http://localhost:3000"))

        # Send magic link email
        supabase.auth.sign_in_with_otp({
            "email": data.email,
            "options": {
                "email_redirect_to": f"{redirect_url}/auth/callback",
                "data": {
                    "full_name": data.full_name or ""
                }
            }
        })

        # Try to create/update user profile if user exists
        try:
            # Get user by email to check if they exist
            # Note: In magic link flow, user might not exist until they click the link
            if USE_SELF_HOSTED_PG and data.full_name:
                # We'll create the profile when they verify the token
                pass
        except Exception as e:
            logger.warning(f"Profile check failed (user may not exist yet): {e}")

        return MagicLinkResponse(
            message="Check your email for a magic link to log in!",
            email=data.email
        )
    except Exception as e:
        logger.error(f"Magic link error: {e}")
        # Don't reveal if email exists or not (security)
        return MagicLinkResponse(
            message="If an account exists, a magic link has been sent to your email.",
            email=data.email
        )


@router.post("/verify", response_model=UserProfile)
async def verify_magic_link(data: VerifyTokenRequest, request: Request):
    """
    Verify magic link token and create user session.

    This endpoint is called after the user clicks the magic link from their email.
    The frontend should extract the access_token and refresh_token from the URL
    and send them here to create a session.
    """
    try:
        supabase = get_supabase()

        # Set the session with the tokens from the magic link
        auth_response = supabase.auth.set_session({
            "access_token": data.access_token,
            "refresh_token": data.refresh_token
        })

        if not auth_response.user:
            raise HTTPException(status_code=401, detail="Invalid magic link token")

        # Create/update user profile in local PostgreSQL if using self-hosted
        if USE_SELF_HOSTED_PG:
            from app.database import create_user_profile, get_user_profile

            # Check if profile exists
            existing = get_user_profile(auth_response.user.id)

            if not existing:
                # Create new profile
                user_metadata = auth_response.user.user_metadata or {}
                create_user_profile(
                    user_id=auth_response.user.id,
                    full_name=user_metadata.get("full_name") or user_metadata.get("name"),
                    email=auth_response.user.email
                )
                profile = {
                    "full_name": user_metadata.get("full_name") or user_metadata.get("name"),
                    "avatar_url": None,
                    "subscription_tier": "free"
                }
            else:
                profile = existing
        else:
            # Using Supabase database, profile already exists via trigger
            profile = {
                "full_name": auth_response.user.user_metadata.get("full_name") if auth_response.user.user_metadata else None,
                "avatar_url": auth_response.user.user_metadata.get("avatar_url") if auth_response.user.user_metadata else None,
                "subscription_tier": "free"
            }

        return UserProfile(
            id=auth_response.user.id,
            email=auth_response.user.email,
            full_name=profile.get("full_name"),
            avatar_url=profile.get("avatar_url"),
            subscription_tier=profile.get("subscription_tier", "free"),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Token verification error: {e}")
        raise HTTPException(status_code=401, detail="Invalid or expired magic link")


@router.post("/logout")
async def logout(request: Request):
    """
    Logout a user by invalidating their session.
    Expects Authorization header with Bearer token.
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing authorization header")

    try:
        supabase = get_supabase()
        supabase.auth.sign_out()
        return {"message": "Logged out successfully"}
    except Exception as e:
        logger.error(f"Logout error: {e}")
        raise HTTPException(status_code=400, detail="Failed to logout")


@router.get("/me", response_model=UserProfile)
async def get_current_user(request: Request):
    """
    Get the current authenticated user's profile.
    Expects Authorization header with Bearer token.
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing authorization header")

    token = auth_header.split(" ")[1]
    try:
        supabase = get_supabase()
        # Verify token and get user
        user_response = supabase.auth.get_user(token)
        if not user_response.user:
            raise HTTPException(status_code=401, detail="Invalid token")

        # Get user profile from self-hosted PostgreSQL or Supabase
        if USE_SELF_HOSTED_PG:
            from app.database import get_user_profile
            profile = get_user_profile(user_response.user.id) or {}
        else:
            profile_response = supabase.table("user_profiles").select("*").eq("id", user_response.user.id).single().execute()
            profile = profile_response.data[0] if profile_response.data else {}

        return UserProfile(
            id=user_response.user.id,
            email=user_response.user.email,
            full_name=profile.get("full_name"),
            avatar_url=profile.get("avatar_url"),
            subscription_tier=profile.get("subscription_tier", "free"),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get user error: {e}")
        raise HTTPException(status_code=401, detail="Invalid authentication token")


@router.post("/refresh")
async def refresh_token(request: Request):
    """
    Refresh an access token using a refresh token.
    Expects Authorization header with Bearer refresh_token.
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing authorization header")

    refresh_token = auth_header.split(" ")[1]
    try:
        supabase = get_supabase()
        auth_response = supabase.auth.refresh_session(refresh_token)

        if not auth_response.session:
            raise HTTPException(status_code=401, detail="Invalid refresh token")

        return {
            "access_token": auth_response.session.access_token,
            "refresh_token": auth_response.session.refresh_token
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Token refresh error: {e}")
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")
