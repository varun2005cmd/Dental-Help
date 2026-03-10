#!/usr/bin/env python3
"""
Patches the existing ElevenLabs agent with the updated system prompt AND tool timeouts.
Run whenever the system prompt changes without needing to recreate the agent.

    python scripts/update_agent_prompt.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

API_KEY     = os.environ.get("ELEVENLABS_API_KEY", "").strip()
AGENT_ID    = os.environ.get("AGENT_ID", "").strip()
BACKEND_URL = os.environ.get("BACKEND_URL", "https://demodental.onrender.com").strip().rstrip("/")

if not API_KEY:
    print("ERROR: ELEVENLABS_API_KEY not set", file=sys.stderr); sys.exit(1)
if not AGENT_ID:
    print("ERROR: AGENT_ID not set — run setup_agent.py first", file=sys.stderr); sys.exit(1)

# Import the same SYSTEM_PROMPT from setup_agent.py
sys.path.insert(0, str(ROOT))
from scripts.setup_agent import SYSTEM_PROMPT

HEADERS = {"xi-api-key": API_KEY, "Content-Type": "application/json"}

# Full tool definitions with 30s timeouts (up from 15s) to survive Render cold starts
TOOLS = [
    {
        "type": "webhook",
        "name": "check_availability",
        "description": (
            "Check available appointment slots at Dental Help. "
            "Call this whenever the patient asks about availability or "
            "before confirming a booking."
        ),
        "response_timeout_secs": 30,
        "disable_interruptions": False,
        "execution_mode": "immediate",
        "api_schema": {
            "url": f"{BACKEND_URL}/api/slots",
            "method": "GET",
            "query_params_schema": {
                "properties": {
                    "date": {
                        "type": "string",
                        "description": (
                            "Optional date filter in YYYY-MM-DD format. "
                            "Omit to get all upcoming slots."
                        ),
                    }
                },
            },
        },
    },
    {
        "type": "webhook",
        "name": "book_appointment",
        "description": (
            "Book a confirmed appointment slot. "
            "Only call this AFTER the patient has confirmed their name, "
            "service, and chosen time slot."
        ),
        "response_timeout_secs": 30,
        "disable_interruptions": False,
        "execution_mode": "immediate",
        "api_schema": {
            "url": f"{BACKEND_URL}/api/book-appointment",
            "method": "POST",
            "request_body_schema": {
                "type": "object",
                "properties": {
                    "patient_name": {
                        "type": "string",
                        "description": "Full name of the patient",
                    },
                    "service_type": {
                        "type": "string",
                        "description": (
                            "Exact service name from the clinic list, "
                            "e.g. 'Routine Checkup', 'Teeth Cleaning'"
                        ),
                    },
                    "appointment_time": {
                        "type": "string",
                        "description": (
                            "ISO-8601 datetime of the chosen slot, "
                            "e.g. '2026-03-12T14:00:00+00:00'"
                        ),
                    },
                    "conversation_id": {
                        "type": "string",
                        "description": "Current ElevenLabs conversation ID",
                    },
                },
                "required": ["patient_name", "service_type", "appointment_time"],
            },
        },
    },
]


def main():
    print(f"Patching agent {AGENT_ID[:20]}…")
    print(f"  Backend URL : {BACKEND_URL}")
    print(f"  Tool timeouts: 30s each")

    payload = {
        "conversation_config": {
            "turn": {
                "turn_timeout": 10,
                "silence_end_call_timeout": 30,
            },
            "agent": {
                "prompt": {
                    "prompt": SYSTEM_PROMPT,
                    "tools": TOOLS,
                }
            }
        }
    }

    with httpx.Client(headers=HEADERS, timeout=30) as client:
        resp = client.patch(
            f"https://api.elevenlabs.io/v1/convai/agents/{AGENT_ID}",
            json=payload,
        )

    if resp.status_code not in (200, 201):
        print(f"ERROR [{resp.status_code}]: {resp.text}", file=sys.stderr)
        sys.exit(1)

    print("✓ Agent prompt + tools updated successfully")
    print(f"  Agent ID: {AGENT_ID}")

if __name__ == "__main__":
    main()
