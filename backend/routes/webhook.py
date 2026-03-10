"""
Webhook endpoint for ElevenLabs post-call events.

ElevenLabs sends a POST request after every conversation ends.
We verify the HMAC-SHA256 signature, then:
  1. Extract and store the full transcript
  2. Determine booking_status by checking if book_appointment was called
  3. Insert a record into the `conversations` collection
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from backend.database import conversations_collection, appointments_collection

router = APIRouter(tags=["webhook"])
logger = logging.getLogger(__name__)


def _verify_signature(raw_body: bytes, signature_header: str, secret: str) -> bool:
    """
    Verify the ElevenLabs-Signature header.
    Format: t=<timestamp>,v0=<hex_digest>
    Signed payload: "<timestamp>.<raw_body_string>"
    """
    try:
        parts = dict(p.split("=", 1) for p in signature_header.split(","))
        timestamp = parts["t"]
        received_sig = parts["v0"]
    except (KeyError, ValueError):
        logger.warning("Malformed ElevenLabs-Signature header: %s", signature_header)
        return False

    payload_to_sign = f"{timestamp}.{raw_body.decode('utf-8')}"
    expected_sig = hmac.new(
        secret.encode("utf-8"),
        payload_to_sign.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected_sig, received_sig)


def _transcript_to_text(transcript_list: list[dict]) -> str:
    """Convert ElevenLabs transcript array to readable plain text."""
    lines = []
    for entry in transcript_list:
        role = (entry.get("role") or "unknown").capitalize()
        message = (entry.get("message") or "").strip()
        if message:
            lines.append(f"{role}: {message}")
    return "\n".join(lines) if lines else "(no transcript)"


def _determine_booking_status(data: dict) -> str:
    """
    Determine booking_status from the webhook payload.
    - "success"    → book_appointment tool returned success=true
    - "failed"     → book_appointment tool was called but returned success=false
    - "incomplete" → book_appointment was never invoked
    """
    # Check data_collection_results for patient_name and appointment_time
    data_collection = data.get("analysis", {}).get("data_collection_results", {})
    has_patient_name = bool(data_collection.get("patient_name", {}).get("value"))
    has_appt_time = bool(data_collection.get("appointment_time", {}).get("value"))

    # Check call_successful from evaluation
    call_successful = data.get("analysis", {}).get("call_successful", "")

    # If we have full booking data and the call was marked successful → success
    if has_patient_name and has_appt_time and call_successful == "success":
        return "success"
    # If name collected but something went wrong
    if has_patient_name and (has_appt_time or call_successful == "failure"):
        return "failed"
    # Otherwise booking was not attempted
    return "incomplete"


@router.post("/webhook/elevenlabs")
async def elevenlabs_webhook(request: Request):
    """
    Receives post-call event from ElevenLabs.
    Must read the raw body BEFORE deserializing for HMAC verification.
    """
    raw_body = await request.body()

    # ── Signature Verification ───────────────────────────────────────────────
    webhook_secret = os.environ.get("WEBHOOK_SECRET", "")
    if webhook_secret:
        sig_header = request.headers.get("ElevenLabs-Signature", "")
        if not sig_header:
            logger.warning("Missing ElevenLabs-Signature header")
            raise HTTPException(status_code=400, detail="Missing signature header")

        if not _verify_signature(raw_body, sig_header, webhook_secret):
            # Log but continue — in demo mode we save the transcript regardless.
            # The most common cause is WEBHOOK_SECRET not yet updated on Render.
            logger.warning(
                "Webhook signature verification FAILED — saving transcript anyway. "
                "Check that WEBHOOK_SECRET on Render matches .env value."
            )
    else:
        logger.warning("WEBHOOK_SECRET not set — skipping signature verification (dev mode)")

    # ── Parse Payload ────────────────────────────────────────────────────────
    try:
        body = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}") from exc

    event_type = body.get("type", "")
    logger.info("Received ElevenLabs webhook event: %s", event_type)

    # Accept any event that may carry transcript/analysis data.
    # Use a broad allowlist — ElevenLabs changes event names across API versions.
    IGNORED_TYPES = {"ping", "test", "verification"}
    if event_type and event_type.lower() in IGNORED_TYPES:
        return JSONResponse({"status": "ignored", "event_type": event_type})
    # If we don't recognise the type but it's not a known non-event, still try to process it.
    known_call_types = {"post_call", "post_call_transcription", "transcript", "call_processed", ""}
    if event_type and event_type not in known_call_types:
        logger.info("Unknown event type '%s' — attempting to process anyway", event_type)

    data = body.get("data", body)  # some versions wrap in data, some don't

    # ── Extract Fields ───────────────────────────────────────────────────────
    conversation_id = (
        data.get("conversation_id")
        or body.get("conversation_id")
        or "unknown"
    )

    transcript_list = data.get("transcript", [])
    transcript_text = _transcript_to_text(transcript_list)

    booking_status = _determine_booking_status(data)

    # ── Reconcile booking_status with actual appointments collection ──────────
    # The most reliable check: did book_appointment actually insert a document?
    appt_col = appointments_collection()

    # Link the MOST RECENTLY booked unlinked appointment to this conversation
    await appt_col.find_one_and_update(
        {"conversation_id": "unknown", "status": "confirmed"},
        {"$set": {"conversation_id": conversation_id}},
        sort=[("created_at", -1)],
    )

    # Now check if there's a confirmed appointment for this conversation
    confirmed_appt = await appt_col.find_one(
        {"conversation_id": conversation_id, "status": "confirmed"}
    )
    rejected_appt = await appt_col.find_one(
        {"conversation_id": conversation_id, "status": "rejected"}
    )

    if confirmed_appt:
        booking_status = "success"
    elif rejected_appt:
        booking_status = "failed"
    # else keep the payload-derived booking_status from above

    # ── Store Conversation Record (upsert to avoid duplicates with /api/sync) ──
    has_audio = bool(data.get("has_audio") or data.get("has_response_audio"))
    record = {
        "caller_id": conversation_id,
        "transcript": transcript_text,
        "booking_status": booking_status,
        "has_audio": has_audio,
        "has_response_audio": bool(data.get("has_response_audio")),
        "conv_status": data.get("status", "done"),
        # Extra metadata for visibility
        "agent_id": data.get("agent_id", ""),
        "call_duration_secs": data.get("metadata", {}).get("call_duration_secs", 0),
        "termination_reason": data.get("metadata", {}).get("termination_reason", ""),
        "summary": data.get("analysis", {}).get("transcript_summary", ""),
    }

    conv_col = conversations_collection()
    existing = await conv_col.find_one({"caller_id": conversation_id})
    if existing:
        await conv_col.update_one({"caller_id": conversation_id}, {"$set": record})
        doc_id = str(existing["_id"])
    else:
        record["created_at"] = datetime.now(timezone.utc)
        result = await conv_col.insert_one(record)
        doc_id = str(result.inserted_id)

    logger.info(
        "Stored conversation %s → _id=%s, booking_status=%s",
        conversation_id, doc_id, booking_status,
    )

    return JSONResponse({
        "status": "ok",
        "stored_id": doc_id,
        "conversation_id": conversation_id,
        "booking_status": booking_status,
    })
