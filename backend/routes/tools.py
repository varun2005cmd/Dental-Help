"""
Server tool endpoints called by the ElevenLabs agent during a conversation.

Tools configured on the agent:
  1. check_availability  →  GET  /api/slots
  2. book_appointment    →  POST /api/book-appointment
"""
from __future__ import annotations

import os
import random
from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from backend.clinic_data import ALL_SLOTS, SERVICE_NAMES, CLINIC_NAME, CLINIC_ADDRESS, CLINIC_PHONE, CLINIC_HOURS, SERVICES, DOCTORS
from backend.database import appointments_collection
from backend.models import BookAppointmentRequest

router = APIRouter(tags=["tools"])


# ─── 1. Check Availability ────────────────────────────────────────────────────

@router.get("/api/slots")
async def check_availability(date: Optional[str] = Query(None, description="YYYY-MM-DD")):
    """
    Returns available appointment slots in a clean, LLM-readable format.
    The agent calls this to present options to the patient.
    'date' is optional; if absent, returns all upcoming slots (up to 20).
    """
    # Pull already-booked datetimes from MongoDB
    appointments_col = appointments_collection()
    booked_isos: set[str] = set()
    async for doc in appointments_col.find({"status": "confirmed"}, {"appointment_time": 1}):
        if "appointment_time" in doc:
            dt = doc["appointment_time"]
            if isinstance(dt, datetime):
                # Normalise to UTC ISO without microseconds
                booked_isos.add(dt.replace(microsecond=0, tzinfo=timezone.utc).isoformat())
            else:
                booked_isos.add(str(dt)[:19].replace(" ", "T") + "+00:00")

    # Re-generate fresh slots (14-day window so there's always plenty)
    from backend.clinic_data import _generate_slots
    fresh_slots = _generate_slots(days_ahead=14)

    available = []
    for slot in fresh_slots:
        # Normalise slot time for comparison
        iso_norm = slot["datetime_iso"][:19].replace(" ", "T") + "+00:00"
        if iso_norm in booked_isos:
            continue
        if date and not slot["datetime_iso"].startswith(date):
            continue
        available.append({
            "slot_id": slot["slot_id"],
            "datetime_iso": slot["datetime_iso"],   # used when calling book_appointment
            "label": slot["display"],               # human-readable, read this to the caller
        })
        if len(available) >= 20:
            break

    if not available:
        return JSONResponse({
            "available": False,
            "message": "No available slots found for the requested period. Please ask the patient for a different date.",
            "slots": [],
        })

    return JSONResponse({
        "available": True,
        "slots": available,
        "total": len(available),
        "instruction": (
            "Read 3-5 of these slots to the caller as options. "
            "When the caller chooses one, use its datetime_iso value when calling book_appointment."
        ),
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

    # Validate service — first try the explicit alias map, then substring fuzzy-match
    SERVICE_ALIASES = {
        "cleaning":        "Teeth Cleaning",
        "teeth cleaning":  "Teeth Cleaning",
        "whitening":       "Teeth Whitening",
        "teeth whitening": "Teeth Whitening",
        "checkup":         "Routine Checkup",
        "check-up":        "Routine Checkup",
        "check up":        "Routine Checkup",
        "routine":         "Routine Checkup",
        "filling":         "Cavity Filling",
        "cavity":          "Cavity Filling",
        "cavity filling":  "Cavity Filling",
        "root canal":      "Root Canal Treatment",
        "root canal treatment": "Root Canal Treatment",
        "x-ray":           "Dental X-Ray",
        "xray":            "Dental X-Ray",
        "x ray":           "Dental X-Ray",
        "extraction":      "Tooth Extraction",
        "tooth extraction":"Tooth Extraction",
        "pull":            "Tooth Extraction",
        "braces":          "Braces Consultation",
        "consultation":    "Braces Consultation",
        "braces consultation": "Braces Consultation",
        "emergency":       "Emergency Dental Care",
        "emergency dental": "Emergency Dental Care",
        "emergency care":  "Emergency Dental Care",
    }
    lower_input = payload.service_type.strip().lower()
    matched_service = SERVICE_ALIASES.get(lower_input, payload.service_type)
    if matched_service not in SERVICE_NAMES:
        # Substring fuzzy-match as fallback
        for svc in SERVICE_NAMES:
            if lower_input in svc.lower() or svc.lower() in lower_input:
                matched_service = svc
                break
    if matched_service not in SERVICE_NAMES:
        matched_service = "Routine Checkup"  # safe default if everything fails

    # Auto-assign a doctor (round-robin based on appointment count)
    total_appts = await appointments_col.count_documents({})
    assigned_doctor = DOCTORS[total_appts % len(DOCTORS)]["name"]

    # Insert appointment
    doc = {
        "conversation_id": payload.conversation_id or "unknown",
        "patient_name": payload.patient_name,
        "service_type": matched_service,
        "appointment_time": appt_dt,
        "doctor": assigned_doctor,
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
                f"{matched_service} on {appt_dt.strftime('%A, %B %d at %I:%M %p UTC')} "
                f"with {assigned_doctor}. "
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
