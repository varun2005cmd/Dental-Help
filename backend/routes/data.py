"""
Read-only endpoints consumed by the frontend to display stored data.
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.database import conversations_collection, appointments_collection

router = APIRouter(tags=["data"])


def _stringify_doc(doc: dict) -> dict:
    """Convert MongoDB document to JSON-serialisable dict."""
    doc["id"] = str(doc.pop("_id"))
    for key, value in doc.items():
        # Convert datetime fields to ISO strings
        if hasattr(value, "isoformat"):
            doc[key] = value.isoformat()
    return doc


@router.get("/api/conversations")
async def get_conversations(limit: int = 50):
    """Return the most recent conversations, newest first."""
    col = conversations_collection()
    cursor = col.find({}).sort("created_at", -1).limit(limit)
    results = []
    async for doc in cursor:
        results.append(_stringify_doc(doc))
    return JSONResponse({"conversations": results, "count": len(results)})


@router.get("/api/appointments")
async def get_appointments(limit: int = 50):
    """Return the most recent appointments, newest first."""
    col = appointments_collection()
    cursor = col.find({}).sort("created_at", -1).limit(limit)
    results = []
    async for doc in cursor:
        results.append(_stringify_doc(doc))
    return JSONResponse({"appointments": results, "count": len(results)})


@router.get("/api/config")
async def get_config():
    """
    Returns public configuration values needed by the frontend.
    (Specifically, the ElevenLabs agent_id so the HTML page can render the widget.)
    """
    import os
    return JSONResponse({
        "agent_id": os.environ.get("AGENT_ID", ""),
        "clinic_name": "Dental Help",
    })


@router.get("/api/health")
async def health():
    """Simple liveness probe used by Railway and for testing."""
    return JSONResponse({"status": "ok", "service": "demodental-backend"})
