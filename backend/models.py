"""
Pydantic models for request/response validation and MongoDB document mapping.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field


# ─── MongoDB Document Models ──────────────────────────────────────────────────

class ConversationRecord(BaseModel):
    """Stored in the `conversations` collection after a call ends."""
    caller_id: str                          # ElevenLabs conversation_id
    transcript: str                          # Full conversation as plain text
    booking_status: Literal["success", "failed", "incomplete"]
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AppointmentRecord(BaseModel):
    """Stored in the `appointments` collection when the agent books a slot."""
    conversation_id: str                    # links back to ConversationRecord
    patient_name: str
    service_type: str
    appointment_time: datetime
    status: Literal["confirmed", "rejected"]
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ─── Tool Request / Response Models ───────────────────────────────────────────

class CheckSlotsRequest(BaseModel):
    date: Optional[str] = None              # YYYY-MM-DD; if None returns all upcoming


class BookAppointmentRequest(BaseModel):
    patient_name: str
    service_type: str
    appointment_time: str                   # ISO-8601 string from the agent
    conversation_id: Optional[str] = None  # forwarded by the agent if configured


class BookAppointmentResponse(BaseModel):
    success: bool
    appointment_id: Optional[str] = None
    message: str


# ─── API Response Models ───────────────────────────────────────────────────────

class ConversationOut(BaseModel):
    id: str
    caller_id: str
    transcript: str
    booking_status: str
    created_at: str


class AppointmentOut(BaseModel):
    id: str
    conversation_id: str
    patient_name: str
    service_type: str
    appointment_time: str
    status: str
    created_at: str
