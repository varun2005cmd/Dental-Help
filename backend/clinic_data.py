"""
Demo clinic data for Dental Help.
This module serves as the single source of truth for all clinic information
used by the ElevenLabs agent and the backend API.
"""
from datetime import datetime, timedelta, timezone

# ─── Clinic Profile ───────────────────────────────────────────────────────────
CLINIC_NAME = "Dental Help"
CLINIC_ADDRESS = "42 Oak Street, Suite 200, Springfield, IL 62701"
CLINIC_PHONE = "(217) 555-0148"
CLINIC_EMAIL = "hello@dentalhelp-demo.com"

CLINIC_HOURS = {
    "Monday":    "9:00 AM – 6:00 PM",
    "Tuesday":   "9:00 AM – 6:00 PM",
    "Wednesday": "9:00 AM – 6:00 PM",
    "Thursday":  "9:00 AM – 6:00 PM",
    "Friday":    "9:00 AM – 6:00 PM",
    "Saturday":  "9:00 AM – 2:00 PM",
    "Sunday":    "Closed",
}

# ─── Services ─────────────────────────────────────────────────────────────────
SERVICES = [
    {"name": "Routine Checkup",       "duration_mins": 30,  "price": 80},
    {"name": "Teeth Cleaning",        "duration_mins": 45,  "price": 120},
    {"name": "Teeth Whitening",       "duration_mins": 60,  "price": 200},
    {"name": "Cavity Filling",        "duration_mins": 45,  "price": 150},
    {"name": "Root Canal Treatment",  "duration_mins": 90,  "price": 850},
    {"name": "Dental X-Ray",          "duration_mins": 20,  "price": 75},
    {"name": "Tooth Extraction",      "duration_mins": 45,  "price": 200},
    {"name": "Braces Consultation",   "duration_mins": 30,  "price": 0},
    {"name": "Emergency Dental Care", "duration_mins": 60,  "price": 250},
]

SERVICE_NAMES = [s["name"] for s in SERVICES]

# ─── Appointment Slot Generator ───────────────────────────────────────────────
# weekday=0(Mon)..4(Fri): slots every 30 min from 9:00–17:30 (last starts 17:30)
# Saturday: 9:00–13:30

SLOT_INTERVAL_MINS = 30


def _generate_slots(days_ahead: int = 7) -> list[dict]:
    """
    Generate all raw available slots for the next `days_ahead` days.
    Returns a list of dicts: { slot_id, datetime_iso, display, weekday }
    """
    slots = []
    now = datetime.now(timezone.utc)
    # Advance to next full hour to avoid stale slots
    start_day = now.replace(hour=0, minute=0, second=0, microsecond=0)

    slot_idx = 0
    for day_offset in range(days_ahead):
        day = start_day + timedelta(days=day_offset)
        weekday = day.weekday()  # 0=Mon … 6=Sun

        if weekday == 6:  # Sunday – clinic is closed
            continue

        if weekday < 5:   # Mon–Fri
            open_h, close_h = 9, 18
        else:             # Saturday
            open_h, close_h = 9, 14

        current = day.replace(hour=open_h, minute=0)
        end_time = day.replace(hour=close_h, minute=0)

        while current < end_time:
            # Skip slots that are in the past
            if current > now:
                slot_id = f"slot_{slot_idx:04d}"
                slots.append({
                    "slot_id": slot_id,
                    "datetime_iso": current.isoformat(),
                    "display": current.strftime("%A, %B %d %Y at %I:%M %p UTC"),
                    "weekday": current.strftime("%A"),
                })
                slot_idx += 1
            current += timedelta(minutes=SLOT_INTERVAL_MINS)

    return slots


# Pre-built slot list (refreshed at import time; fine for a demo system)
ALL_SLOTS: list[dict] = _generate_slots(days_ahead=7)
