"""
Read/write endpoints consumed by the frontend to display and manage stored data.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import httpx
from bson import ObjectId
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from backend.clinic_data import DOCTORS
from backend.database import conversations_collection, appointments_collection

router = APIRouter(tags=["data"])


def _stringify_doc(doc: dict) -> dict:
    """Convert MongoDB document to JSON-serialisable dict."""
    doc["id"] = str(doc.pop("_id"))
    for key, value in doc.items():
        if hasattr(value, "isoformat"):
            doc[key] = value.isoformat()
    if "doctor" not in doc:
        doc["doctor"] = "Unassigned"
    return doc


@router.post("/api/sync")
async def sync_conversations():
    """
    Pull the most recent conversations from ElevenLabs API and store any that
    are missing from MongoDB.  This is the reliable fallback for when the
    post-call webhook times out (e.g. Render free-tier cold start).
    """
    api_key = os.environ.get("ELEVENLABS_API_KEY", "")
    agent_id = os.environ.get("AGENT_ID", "")
    if not api_key:
        return JSONResponse({"synced": 0, "skipped": 0, "error": "ELEVENLABS_API_KEY not set"})

    conv_col = conversations_collection()
    appt_col = appointments_collection()
    synced = 0
    errors = 0

    async with httpx.AsyncClient(timeout=30) as client:
        headers = {"xi-api-key": api_key}
        params = {"page_size": 25}
        if agent_id:
            params["agent_id"] = agent_id

        resp = await client.get(
            "https://api.elevenlabs.io/v1/convai/conversations",
            headers=headers, params=params,
        )
        if resp.status_code != 200:
            return JSONResponse({"synced": 0, "skipped": 0, "error": f"ElevenLabs {resp.status_code}: {resp.text[:200]}"})

        summaries = resp.json().get("conversations", [])
        skipped = 0

        for summary in summaries:
            conv_id = summary.get("conversation_id", "")
            if not conv_id:
                continue

            # Already stored — skip
            if await conv_col.find_one({"caller_id": conv_id}):
                skipped += 1
                continue

            # Fetch full transcript
            try:
                detail_resp = await client.get(
                    f"https://api.elevenlabs.io/v1/convai/conversations/{conv_id}",
                    headers=headers,
                )
                if detail_resp.status_code != 200:
                    errors += 1
                    continue
                detail = detail_resp.json()
            except Exception:
                errors += 1
                continue

            # Build plain-text transcript
            lines = []
            for entry in detail.get("transcript", []):
                role = entry.get("role", "unknown").capitalize()
                msg = entry.get("message", "").strip()
                if msg:
                    lines.append(f"{role}: {msg}")
            transcript_text = "\n".join(lines) if lines else "(no transcript)"

            # Link the most recent unlinked appointment to this conversation
            await appt_col.find_one_and_update(
                {"conversation_id": "unknown", "status": "confirmed"},
                {"$set": {"conversation_id": conv_id}},
                sort=[("created_at", -1)],
            )

            # Determine booking status from actual appointments
            confirmed = await appt_col.find_one({"conversation_id": conv_id, "status": "confirmed"})
            booking_status = "success" if confirmed else "incomplete"

            record = {
                "caller_id": conv_id,
                "transcript": transcript_text,
                "booking_status": booking_status,
                "created_at": datetime.now(timezone.utc),
                "agent_id": detail.get("agent_id", agent_id),
                "call_duration_secs": detail.get("metadata", {}).get("call_duration_secs", 0),
                "termination_reason": detail.get("metadata", {}).get("termination_reason", ""),
                "summary": detail.get("analysis", {}).get("transcript_summary", ""),
            }
            await conv_col.insert_one(record)
            synced += 1

    return JSONResponse({"synced": synced, "skipped": skipped, "errors": errors})



    """Return the most recent conversations, newest first."""
    col = conversations_collection()
    cursor = col.find({}).sort("created_at", -1).limit(limit)
    results = []
    async for doc in cursor:
        results.append(_stringify_doc(doc))
    return JSONResponse({"conversations": results, "count": len(results)})


@router.api_route("/api/conversations/{conv_id}/audio", methods=["GET", "HEAD"])
async def get_conversation_audio(conv_id: str, request: Request):
    """Proxy the ElevenLabs conversation audio so the browser can play it."""
    api_key = os.environ.get("ELEVENLABS_API_KEY", "")
    if not api_key:
        raise HTTPException(status_code=500, detail="ELEVENLABS_API_KEY not set")
    el_url = f"https://api.elevenlabs.io/v1/convai/conversations/{conv_id}/audio"
    async with httpx.AsyncClient(timeout=30) as client:
        if request.method == "HEAD":
            # Lightweight check — just verify audio exists without downloading it
            resp = await client.head(el_url, headers={"xi-api-key": api_key})
            if resp.status_code != 200:
                raise HTTPException(status_code=404, detail="Audio not available yet")
            return Response(status_code=200, headers={"content-type": "audio/mpeg"})
        resp = await client.get(el_url, headers={"xi-api-key": api_key})
    if resp.status_code != 200:
        raise HTTPException(status_code=404, detail="Audio not available yet")
    return Response(
        content=resp.content,
        media_type=resp.headers.get("content-type", "audio/mpeg"),
        headers={"Accept-Ranges": "bytes"},
    )


@router.get("/api/appointments")
async def get_appointments(limit: int = 50):
    """Return the most recent appointments, newest first."""
    col = appointments_collection()
    cursor = col.find({}).sort("created_at", -1).limit(limit)
    results = []
    async for doc in cursor:
        results.append(_stringify_doc(doc))
    return JSONResponse({"appointments": results, "count": len(results)})


@router.delete("/api/appointments/{appt_id}")
async def delete_appointment(appt_id: str):
    """Manually delete an appointment by its MongoDB ObjectId."""
    try:
        oid = ObjectId(appt_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid appointment ID")
    col = appointments_collection()
    result = await col.delete_one({"_id": oid})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Appointment not found")
    return JSONResponse({"status": "deleted", "id": appt_id})


class DoctorUpdate(BaseModel):
    doctor: str


@router.patch("/api/appointments/{appt_id}/doctor")
async def update_appointment_doctor(appt_id: str, body: DoctorUpdate):
    """Reassign a doctor to an appointment."""
    try:
        oid = ObjectId(appt_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid appointment ID")
    if body.doctor not in [d["name"] for d in DOCTORS]:
        raise HTTPException(status_code=400, detail="Unknown doctor name")
    col = appointments_collection()
    result = await col.update_one({"_id": oid}, {"$set": {"doctor": body.doctor}})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Appointment not found")
    return JSONResponse({"status": "updated", "doctor": body.doctor})


@router.get("/api/doctors")
async def get_doctors():
    return JSONResponse({"doctors": DOCTORS})


@router.get("/api/config")
async def get_config():
    return JSONResponse({
        "agent_id": os.environ.get("AGENT_ID", ""),
        "clinic_name": "Dental Help",
    })


@router.get("/api/health")
async def health():
    return JSONResponse({"status": "ok", "service": "demodental-backend"})
