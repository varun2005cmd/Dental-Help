"""
Server tool endpoints called by the ElevenLabs agent during a conversation.

Tools configured on the agent:
  1. check_availability  →  GET  /api/slots
  2. book_appointment    →  POST /api/book-appointment
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from backend.clinic_data import ALL_SLOTS, SERVICE_NAMES, CLINIC_NAME, CLINIC_ADDRESS, CLINIC_PHONE, CLINIC_HOURS, SERVICES
from backend.database import appointments_collection
from backend.models import BookAppointmentRequest

router = APIRouter(tags=["tools"])


# ─── 1. Check Availability ────────────────────────────────────────────────────

@router.get("/api/slots")
async def check_availability(date: Optional[str] = Query(None, description="YYYY-MM-DD")):
    """
    Returns available appointment slots.
    The agent calls this to present options to the patient.
    'date' is optional; if absent, returns all upcoming slots (up to 20).
    """
    # Pull already-booked datetimes from MongoDB
    appointments_col = appointments_collection()
    booked_cursor = appointments_col.find(
        {"status": "confirmed"},
        {"appointment_time": 1}
    )
    booked_isos: set[str] = set()
    async for doc in booked_cursor:
        if "appointment_time" in doc:
            booked_isos.add(doc["appointment_time"].replace(microsecond=0).isoformat() if isinstance(doc["appointment_time"], datetime) else str(doc["appointment_time"]))

    # Re-generate fresh slots from clinic_data (avoids stale module-level cache)
    from backend.clinic_data import _generate_slots
    fresh_slots = _generate_slots(days_ahead=7)

    # Filter by date if provided
    available = []
    for slot in fresh_slots:
        slot_dt_iso = slot["datetime_iso"].split(".")[0] + "+00:00"  # normalise
        if slot_dt_iso in booked_isos or slot["datetime_iso"] in booked_isos:
            continue
        if date and not slot["datetime_iso"].startswith(date):
            continue
        available.append(slot)
        if len(available) >= 20:
            break

    return JSONResponse({
        "clinic": CLINIC_NAME,
        "available_slots": available,
        "total": len(available),
        "note": "All times are UTC. Please confirm the slot_id when booking.",
    })


# ─── 2. Book Appointment ──────────────────────────────────────────────────────

@router.post("/api/book-appointment")
async def book_appointment(payload: BookAppointmentRequest):
    """
    Books an appointment slot.
    The agent calls this once it has collected: patient_name, service_type, appointment_time.
    """
    appointments_col = appointments_collection()

    # Parse appointment_time
    try:
        # Handle various ISO formats the LLM might produce
        raw_time = payload.appointment_time.strip()
        # Replace space with T for ISO compliance
        raw_time = raw_time.replace(" ", "T")
        appt_dt = datetime.fromisoformat(raw_time)
        if appt_dt.tzinfo is None:
            appt_dt = appt_dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return JSONResponse(
            status_code=200,  # return 200 so the agent gets the message
            content={
                "success": False,
                "appointment_id": None,
                "message": (
                    f"I'm sorry, I couldn't parse the time '{payload.appointment_time}'. "
                    "Please ask the patient to confirm a specific slot from the available list."
                ),
            },
        )

    # Check if slot is already taken
    existing = await appointments_col.find_one({
        "appointment_time": appt_dt,
        "status": "confirmed",
    })
    if existing:
        return JSONResponse(
            status_code=200,
            content={
                "success": False,
                "appointment_id": None,
                "message": (
                    "That time slot is already booked. "
                    "Please offer the patient another available slot."
                ),
            },
        )

    # Validate service
    matched_service = payload.service_type
    if payload.service_type not in SERVICE_NAMES:
        # Fuzzy-match: accept if any service name contains the input (case-insensitive)
        lower_input = payload.service_type.lower()
        for svc in SERVICE_NAMES:
            if lower_input in svc.lower() or svc.lower() in lower_input:
                matched_service = svc
                break

    # Insert appointment
    doc = {
        "conversation_id": payload.conversation_id or "unknown",
        "patient_name": payload.patient_name,
        "service_type": matched_service,
        "appointment_time": appt_dt,
        "status": "confirmed",
        "created_at": datetime.now(timezone.utc),
    }
    result = await appointments_col.insert_one(doc)
    appt_id = str(result.inserted_id)

    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "appointment_id": appt_id,
            "message": (
                f"Appointment confirmed! {payload.patient_name} is booked for "
                f"{matched_service} on {appt_dt.strftime('%A, %B %d at %I:%M %p UTC')}. "
                f"Confirmation ID: {appt_id}. "
                f"Our address is {CLINIC_ADDRESS}. Phone: {CLINIC_PHONE}."
            ),
        },
    )


# ─── 3. Clinic Info (bonus: agent can call if needed) ─────────────────────────

@router.get("/api/clinic-info")
async def clinic_info():
    return JSONResponse({
        "name": CLINIC_NAME,
        "address": CLINIC_ADDRESS,
        "phone": CLINIC_PHONE,
        "hours": CLINIC_HOURS,
        "services": SERVICES,
    })
