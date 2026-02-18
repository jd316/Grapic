"""Event management routes."""

import io
import qrcode
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.models import EventCreate, EventResponse, EventJoin, OrganizerJoin, EventUpdate, StatusResponse
from app.database import create_event, get_event, get_event_by_code, get_event_by_organizer_code, delete_event, update_event, get_events_by_user
from app.services.storage import delete_event_files
from app.config import BASE_URL, USE_SUPABASE
from app.auth_middleware import get_user_id

router = APIRouter(prefix="/api/events", tags=["events"])


def require_auth(request: Request) -> str:
    """Helper to require authentication and return user_id."""
    if USE_SUPABASE:
        user_id = get_user_id(request)
        if not user_id:
            raise HTTPException(status_code=401, detail="Authentication required")
        return user_id
    # For SQLite mode, no auth required (backward compatibility)
    return None


@router.post("", response_model=EventResponse)
def api_create_event(data: EventCreate, request: Request):
    """Create a new event space. Requires authentication when using Supabase."""
    user_id = require_auth(request) if USE_SUPABASE else None
    event = create_event(
        name=data.name,
        description=data.description,
        expires_in_days=data.expires_in_days,
        user_id=user_id,
    )
    return event


@router.get("", response_model=list[EventResponse])
def api_list_events(request: Request):
    """List all events for the authenticated user."""
    if not USE_SUPABASE:
        # For SQLite mode, return empty list (not supported)
        return []

    user_id = get_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    return get_events_by_user(user_id)


@router.get("/{event_id}", response_model=EventResponse)
def api_get_event(event_id: str):
    """Get event details by ID."""
    event = get_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


@router.patch("/{event_id}", response_model=EventResponse)
def api_update_event(event_id: str, data: EventUpdate, request: Request):
    """Update event details (name, description, expiration). Requires authentication when using Supabase."""
    if USE_SUPABASE:
        user_id = get_user_id(request)
        if not user_id:
            raise HTTPException(status_code=401, detail="Authentication required")

        event = get_event(event_id)
        if not event:
            raise HTTPException(status_code=404, detail="Event not found")

        # Check ownership
        if event.get("user_id") != user_id:
            raise HTTPException(status_code=403, detail="You don't have permission to update this event")

    updated = update_event(
        event_id,
        name=data.name,
        description=data.description,
        expires_in_days=data.expires_in_days,
    )
    return updated


@router.delete("/{event_id}", response_model=StatusResponse)
def api_delete_event(event_id: str, request: Request):
    """Delete an event and all associated data. Requires authentication when using Supabase."""
    if USE_SUPABASE:
        user_id = get_user_id(request)
        if not user_id:
            raise HTTPException(status_code=401, detail="Authentication required")

        event = get_event(event_id)
        if not event:
            raise HTTPException(status_code=404, detail="Event not found")

        # Check ownership
        if event.get("user_id") != user_id:
            raise HTTPException(status_code=403, detail="You don't have permission to delete this event")
    else:
        event = get_event(event_id)
        if not event:
            raise HTTPException(status_code=404, detail="Event not found")

    delete_event_files(event_id)
    delete_event(event_id)
    return {"status": "ok", "message": f"Event '{event['name']}' deleted"}


@router.post("/join", response_model=EventResponse)
def api_join_event(data: EventJoin):
    """Join an event as attendee (for finding photos). Uses attendee access code."""
    event = get_event_by_code(data.access_code)
    if not event:
        raise HTTPException(status_code=404, detail="Invalid access code")
    ev = get_event(event["id"])
    ev.pop("organizer_code", None)
    ev.pop("user_id", None)  # Don't expose user_id to attendees
    return ev


@router.post("/organizer-join", response_model=EventResponse)
def api_organizer_join(data: OrganizerJoin, request: Request):
    """Log in as organizer (for dashboard). Uses organizer code only."""
    event = get_event_by_organizer_code(data.organizer_code)
    if not event:
        raise HTTPException(status_code=404, detail="Invalid organizer code")

    # When using Supabase, verify ownership
    if USE_SUPABASE:
        user_id = get_user_id(request)
        if user_id and event.get("user_id") != user_id:
            raise HTTPException(status_code=403, detail="You don't have permission to access this event")

    return get_event(event["id"])


@router.get("/{event_id}/qr")
def api_get_qr_code(event_id: str):
    """Generate a QR code containing the event access code."""
    event = get_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    # QR code contains the full join URL so scanners can open or parse it
    join_url = f"{BASE_URL.rstrip('/')}/join/{event['access_code']}"
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(join_url)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    return StreamingResponse(buf, media_type="image/png")
