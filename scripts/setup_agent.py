#!/usr/bin/env python3
"""
One-time setup script: creates the ElevenLabs workspace webhook and Conversational AI agent.

Run AFTER the backend is deployed and BACKEND_URL is known:

    python scripts/setup_agent.py

Required env vars (either in .env or shell):
    ELEVENLABS_API_KEY   — your ElevenLabs API key
    BACKEND_URL          — public HTTPS URL of the deployed backend
                          (e.g. https://demodental.up.railway.app)

Writes back to .env:
    WEBHOOK_SECRET       — HMAC secret returned by ElevenLabs after webhook registration
    AGENT_ID             — agent_id returned after agent creation
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import httpx
from dotenv import dotenv_values, load_dotenv

# ─── Config ───────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"

load_dotenv(ENV_FILE)

API_KEY = os.environ.get("ELEVENLABS_API_KEY", "").strip()
BACKEND_URL = os.environ.get("BACKEND_URL", "").strip().rstrip("/")

ELEVEN_BASE = "https://api.elevenlabs.io"
HEADERS = {
    "xi-api-key": API_KEY,
    "Content-Type": "application/json",
}

# ─── System Prompt ────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are a friendly and professional dental receptionist named "Aria" at Dental Help.

== CLINIC INFORMATION ==
Name: Dental Help
Address: 42 Oak Street, Suite 200, Springfield, IL 62701
Phone: (217) 555-0148
Hours: Monday–Friday 9:00 AM – 6:00 PM | Saturday 9:00 AM – 2:00 PM | Sunday: Closed

== SERVICES & PRICES ==
- Routine Checkup: $80 (30 min)
- Teeth Cleaning: $120 (45 min)
- Teeth Whitening: $200 (60 min)
- Cavity Filling: $150 (45 min)
- Root Canal Treatment: $850 (90 min)
- Dental X-Ray: $75 (20 min)
- Tooth Extraction: $200 (45 min)
- Braces Consultation: FREE (30 min)
- Emergency Dental Care: $250 (60 min)

== YOUR ROLE ==
1. Warmly greet the caller.
2. Answer any questions about services, pricing, hours, or location.
3. If they want to book an appointment:
   a. Ask for their FULL NAME.
   b. Ask which SERVICE they need (offer the list if they are unsure).
   c. Ask for their PREFERRED DATE AND TIME.
   d. Call the check_availability tool to confirm a slot is open.
   e. Offer available slots and let them choose.
   f. Confirm their choice, then call the book_appointment tool with:
      - patient_name (string)
      - service_type (string — must match one from the list above)
      - appointment_time (ISO-8601 string, e.g. "2026-03-10T14:00:00+00:00")
      - conversation_id (string — use the current conversation ID if available, else "unknown")
   g. Read the confirmation message back to the caller, including the Confirmation ID.
4. Always be empathetic — patients may be anxious about dental visits.
5. Do NOT make up slot availability. Always call check_availability first.
6. If a booking fails, apologise and offer alternative times.
7. End the call warmly.
"""

# ─── Helpers ──────────────────────────────────────────────────────────────────

def _update_env(key: str, value: str) -> None:
    """Write or update a key=value line in the .env file."""
    content = ENV_FILE.read_text() if ENV_FILE.exists() else ""
    pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
    new_line = f'{key}="{value}"'
    if pattern.search(content):
        content = pattern.sub(new_line, content)
    else:
        content = content.rstrip("\n") + f"\n{new_line}\n"
    ENV_FILE.write_text(content)
    print(f"  ✓ .env updated: {key}={value}")


def _bail(msg: str) -> None:
    print(f"\n✗ ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


# ─── Step 1: Register Workspace Webhook ──────────────────────────────────────

def register_webhook(client: httpx.Client) -> tuple[str, str]:
    """
    Create a workspace webhook and return (webhook_id, webhook_secret).
    Idempotent: if a webhook with the same URL already exists, returns it.
    """
    webhook_url = f"{BACKEND_URL}/webhook/elevenlabs"
    print(f"\n[1] Registering workspace webhook → {webhook_url}")

    # Check existing webhooks first
    resp = client.get(f"{ELEVEN_BASE}/v1/workspace/webhooks")
    if resp.status_code == 200:
        for wh in resp.json().get("webhooks", []):
            if wh.get("webhook_url") == webhook_url:
                print(f"  ↳ Existing webhook found: {wh['webhook_id']}")
                # We can't retrieve the secret again — the user must have it saved
                existing_secret = os.environ.get("WEBHOOK_SECRET", "")
                if not existing_secret:
                    print("  ⚠ Webhook already exists but WEBHOOK_SECRET is not in .env.")
                    print("    Delete the existing webhook in the ElevenLabs dashboard")
                    print("    and re-run this script, OR set WEBHOOK_SECRET manually.")
                return wh["webhook_id"], existing_secret

    payload = {
        "settings": {
            "auth_type": "hmac",
            "name": "DentalHelp Post-Call Webhook",
            "webhook_url": webhook_url,
        }
    }
    resp = client.post(f"{ELEVEN_BASE}/v1/workspace/webhooks", json=payload)
    if resp.status_code not in (200, 201):
        _bail(f"Webhook registration failed [{resp.status_code}]: {resp.text}")

    data = resp.json()
    webhook_id = data["webhook_id"]
    secret = data.get("webhook_secret", data.get("secret", ""))
    print(f"  ✓ Webhook created: id={webhook_id}")
    _update_env("WEBHOOK_SECRET", secret)
    return webhook_id, secret


# ─── Step 2: Create the Agent ─────────────────────────────────────────────────

def create_agent(client: httpx.Client, webhook_id: str) -> str:
    """Create the ElevenLabs Conversational AI agent and return agent_id."""
    print("\n[2] Creating ElevenLabs Conversational AI agent…")

    agent_payload = {
        "name": "Dental Help Assistant",
        "conversation_config": {
            "asr": {
                "quality": "high",
                "provider": "elevenlabs",
                "keywords": [
                    "appointment", "dental", "cleaning", "filling", "whitening",
                    "extraction", "root canal", "braces", "x-ray", "checkup",
                    "Dental Help",
                ],
            },
            "turn": {
                "turn_timeout": 7,
                "silence_end_call_timeout": 30,
            },
            "tts": {
                "model_id": "eleven_turbo_v2",
                "voice_id": "21m00Tcm4TlvDq8ikWAM",  # Rachel — a stable pre-built ElevenLabs voice
                "stability": 0.5,
                "similarity_boost": 0.8,
                "speed": 1.0,
            },
            "agent": {
                "first_message": (
                    "Thank you for calling Dental Help! "
                    "This is Aria speaking. How can I help you today?"
                ),
                "language": "en",
                "prompt": {
                    "prompt": SYSTEM_PROMPT,
                    "llm": "gpt-4o-mini",
                    "temperature": 0.5,
                    "tools": [
                        {
                            "type": "webhook",
                            "name": "check_availability",
                            "description": (
                                "Check available appointment slots at Dental Help. "
                                "Call this whenever the patient asks about availability or "
                                "before confirming a booking."
                            ),
                            "response_timeout_secs": 15,
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
                            "response_timeout_secs": 15,
                            "disable_interruptions": True,
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
                                                "e.g. '2026-03-10T14:00:00+00:00'"
                                            ),
                                        },
                                        "conversation_id": {
                                            "type": "string",
                                            "description": "Current ElevenLabs conversation ID",
                                        },
                                    },
                                    "required": [
                                        "patient_name",
                                        "service_type",
                                        "appointment_time",
                                    ],
                                },
                            },
                        },
                    ],
                },
                "dynamic_variables": {
                    "dynamic_variable_placeholders": {}
                },
            },
            "conversation": {
                "max_duration_seconds": 600,
                "client_events": [
                    "audio",
                    "user_transcript",
                    "agent_response",
                    "conversation_initiation_metadata",
                ],
                "connection_timeout": 30,
            },
        },
        "platform_settings": {
            "evaluation": {
                "criteria": [
                    {
                        "id": "appointment_booked_criteria",
                        "type": "prompt",
                        "name": "appointment_booked",
                        "conversation_goal_prompt": (
                            "Did the agent successfully collect the patient's full name, "
                            "desired service, and appointment time, and then call the "
                            "book_appointment tool to confirm the booking?"
                        ),
                    }
                ]
            },
            "data_collection": {
                "patient_name": {
                    "type": "string",
                    "description": "The full name of the calling patient",
                },
                "service_type": {
                    "type": "string",
                    "description": "The dental service the patient requested",
                },
                "appointment_time": {
                    "type": "string",
                    "description": "The ISO-8601 datetime of the booked appointment",
                },
            },
            "widget": {
                "variant": "full",
                "placement": "bottom-right",
                "expandable": "always",
                "avatar": {
                    "type": "orb",
                    "color_1": "#2563EB",
                    "color_2": "#60A5FA",
                },
            },
            "workspace_overrides": {
                "webhooks": {
                    "post_call_webhook_id": webhook_id,
                    "events": ["transcript"],
                }
            },
            "auth": {
                "enable_auth": False,
                "allowlist": [],
            },
        },
    }

    resp = client.post(
        f"{ELEVEN_BASE}/v1/convai/agents/create",
        json=agent_payload,
    )
    if resp.status_code not in (200, 201):
        _bail(f"Agent creation failed [{resp.status_code}]: {resp.text}")

    agent_id = resp.json()["agent_id"]
    print(f"  ✓ Agent created: agent_id={agent_id}")
    _update_env("AGENT_ID", agent_id)
    return agent_id


# ─── Step 3: Inject AGENT_ID into frontend config ────────────────────────────

def update_frontend_config(agent_id: str) -> None:
    """Write the agent_id into frontend/config.js so the widget loads it."""
    print("\n[3] Writing agent_id to frontend/config.js…")
    config_path = ROOT / "frontend" / "config.js"
    config_path.write_text(
        f"// Auto-generated by scripts/setup_agent.py — do not edit manually\n"
        f'window.DEMODENTAL_CONFIG = {{ agentId: "{agent_id}" }};\n'
    )
    print(f"  ✓ Written: {config_path}")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 60)
    print("  Dental Help — ElevenLabs Agent Setup")
    print("=" * 60)

    if not API_KEY:
        _bail("ELEVENLABS_API_KEY is not set. Add it to your .env file.")
    if not BACKEND_URL:
        _bail(
            "BACKEND_URL is not set. Deploy the backend first, then set "
            "BACKEND_URL=https://your-app.up.railway.app in .env"
        )
    if not BACKEND_URL.startswith("https://"):
        _bail("BACKEND_URL must be an HTTPS URL (ElevenLabs requires HTTPS for webhooks and tools).")

    print(f"\nAPI key  : {API_KEY[:8]}…")
    print(f"Backend  : {BACKEND_URL}")

    with httpx.Client(headers=HEADERS, timeout=30) as client:
        # Verify API key
        me = client.get(f"{ELEVEN_BASE}/v1/user")
        if me.status_code != 200:
            _bail(f"ElevenLabs API key is invalid or expired [{me.status_code}]: {me.text}")
        user_json = me.json() or {}
        key_info = user_json.get('xi_api_key') or {}
        print(f"\n  ✓ Authenticated as: {key_info.get('name', 'N/A')}")

        webhook_id, _ = register_webhook(client)
        agent_id = create_agent(client, webhook_id)
        update_frontend_config(agent_id)

    print("\n" + "=" * 60)
    print("  Setup complete!")
    print("=" * 60)
    print(f"\n  Agent ID     : {agent_id}")
    print(f"  Webhook ID   : {webhook_id}")
    print(f"\n  Next steps:")
    print(f"  1. Add AGENT_ID and WEBHOOK_SECRET to your Render service env vars")
    print(f"  2. Render will auto-redeploy once env vars are saved")
    print(f"  3. Open {BACKEND_URL} in your browser to test the frontend")
    print(f"  4. Click the chat widget and speak to the agent!")
    print()


if __name__ == "__main__":
    main()
