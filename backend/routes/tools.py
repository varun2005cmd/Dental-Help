"""
Server tool endpoints called by the ElevenLabs agent during a conversation.

Tools configured on the agent:
  1. check_availability  →  GET  /api/slots
  2. book_appointment    →  POST /api/book-appointment
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from backend.clinic_data import SERVICE_NAMES, CLINIC_NAME, CLINIC_ADDRESS, CLINIC_PHONE, CLINIC_HOURS, SERVICES, DOCTORS
from backend.database import appointments_collection
from backend.models import BookAppointmentRequest

router = APIRouter(tags=["tools"])
logger = logging.getLogger(__name__)


# ─── 1. Check Availability ────────────────────────────────────────────────────

@router.get("/api/slots")
async def check_availability(date: Optional[str] = Query(None, description="YYYY-MM-DD")):
    """
    Returns available appointment slots. No DB call — fast by design.
    Booked slots are excluded by the duplicate-check in book_appointment.
    """
    from backend.clinic_data import _generate_slots
    fresh_slots = _generate_slots(days_ahead=14)

    available = []
    for slot in fresh_slots:
        if date and not slot["datetime_iso"].startswith(date):
            continue
        available.append({
            "slot_id": slot["slot_id"],
            "datetime_iso": slot["datetime_iso"],
            "label": slot["display"],
        })
        if len(available) >= 20:
            break

    logger.info("check_availability → %d slots returned", len(available))

    if not available:
        return JSONResponse({
            "available": False,
            "message": "No slots available for that date. Ask the patient for a different date.",
            "slots": [],
        })

    return JSONResponse({
        "available": True,
        "slots": available,
        "total": len(available),
        "instruction": (
            "Read 3-4 of these slots to the caller. "
            "When the caller chooses one, pass its datetime_iso to book_appointment."
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

    # Check if slot is already taken (skip if DB is unreachable)
    try:
        existing = await appointments_col.find_one({
            "appointment_time": appt_dt,
            "status": "confirmed",
        })
    except Exception as exc:
        logger.warning("DB find_one failed (skipping duplicate check): %s", exc)
        existing = None
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

    # Auto-assign a doctor (hash of patient name for consistent assignment)
    name_hash = sum(ord(c) for c in payload.patient_name)
    assigned_doctor = DOCTORS[name_hash % len(DOCTORS)]["name"]

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
    try:
        result = await appointments_col.insert_one(doc)
        appt_id = str(result.inserted_id)
    except Exception as exc:
        logger.error("DB insert failed for booking: %s", exc)
        return JSONResponse(
            status_code=200,
            content={
                "success": False,
                "appointment_id": None,
                "message": (
                    f"I have your details, {payload.patient_name}, but I couldn't save the booking right now due to a brief connection issue. "
                    "Could you please call us at (217) 555-0148 to confirm, or try again in a moment?"
                ),
            },
        )

    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "appointment_id": appt_id,
            "message": (
                f"Appointment confirmed! {payload.patient_name} is booked for "
                f"{matched_service} on {appt_dt.strftime('%A, %B %d at %I:%M %p')} UTC "
                f"with {assigned_doctor}. Your confirmation ID is {appt_id[-6:].upper()}."
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
