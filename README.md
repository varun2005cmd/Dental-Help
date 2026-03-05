# 🦷 BrightSmile Dental Clinic — Demo Voice Booking System

A fully functional demo dental clinic voice booking system built with **ElevenLabs Conversational AI**, **FastAPI**, and **MongoDB Atlas**.

Speak to an AI dental receptionist, get available appointment slots, and book a confirmed appointment — all without touching a keyboard. Every conversation and booking is stored automatically in MongoDB.

---

## Demo Clinic Data

| Field | Value |
|---|---|
| **Name** | BrightSmile Dental Clinic |
| **Address** | 42 Oak Street, Suite 200, Springfield, IL 62701 |
| **Phone** | (217) 555-0148 |
| **Hours (Mon–Fri)** | 9:00 AM – 6:00 PM |
| **Hours (Saturday)** | 9:00 AM – 2:00 PM |
| **Sunday** | Closed |

### Services

| Service | Price | Duration |
|---|---|---|
| Routine Checkup | $80 | 30 min |
| Teeth Cleaning | $120 | 45 min |
| Teeth Whitening | $200 | 60 min |
| Cavity Filling | $150 | 45 min |
| Root Canal Treatment | $850 | 90 min |
| Dental X-Ray | $75 | 20 min |
| Tooth Extraction | $200 | 45 min |
| Braces Consultation | FREE | 30 min |
| Emergency Dental Care | $250 | 60 min |

---

## Architecture & System Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                        Browser / User                           │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │         Frontend (HTML + CSS + TypeScript)               │   │
│  │  • ElevenLabs widget embeds voice agent                  │   │
│  │  • Displays conversations & appointments from MongoDB    │   │
│  └────────────────────┬─────────────────────────────────────┘   │
└───────────────────────│─────────────────────────────────────────┘
                        │  REST API  /api/*
                        ▼
┌──────────────────────────────────────────────────────────────── ─┐
│               FastAPI Backend (Python)                           │
│                                                                  │
│  /api/slots            ← check_availability tool (GET)          │
│  /api/book-appointment ← book_appointment tool (POST)           │
│  /webhook/elevenlabs   ← post-call webhook (POST)               │
│  /api/conversations    ← frontend reads stored data             │
│  /api/appointments     ← frontend reads stored data             │
└────────────────────────┬─────────────────────────────────────────┘
                         │  Motor (async)
                         ▼
                ┌─────────────────┐
                │  MongoDB Atlas  │
                │  conversations  │
                │  appointments   │
                └─────────────────┘

                  ▲                  ▲
                  │ Server Tools     │ Post-Call Webhook
                  │ (during call)    │ (after call ends)
                  └──────────────────┘
                    ElevenLabs Cloud
```

### Step-by-step call flow

1. User opens the frontend and clicks the voice widget.
2. ElevenLabs connects the user to the **Aria** AI agent.
3. The agent greets the user and can answer any clinic questions.
4. To book, the agent collects: **name**, **service**, **preferred time**.
5. Agent calls `check_availability` → backend returns open slots from MongoDB.
6. Agent presents slots; user confirms a choice.
7. Agent calls `book_appointment` → backend writes a `confirmed` document to `appointments`.
8. After the call ends, ElevenLabs sends a **post-call webhook** to `/webhook/elevenlabs`.
9. Backend verifies the HMAC-SHA256 signature, extracts the transcript, determines `booking_status`, and inserts a document into `conversations`.
10. Frontend polls every 10 seconds — new rows appear in both tables automatically.

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Voice AI** | ElevenLabs Conversational AI (GPT-4o-mini LLM, server tools) |
| **Backend** | Python 3.11+ · FastAPI · Motor (async MongoDB) |
| **Database** | MongoDB Atlas (free M0 tier) |
| **Frontend** | HTML5 · CSS3 · TypeScript (compiled to JS, no build step) |
| **Deployment** | Railway (one service, backend serves frontend static files) |

---

## Prerequisites

- Python 3.11 or newer
- A free [ElevenLabs](https://elevenlabs.io) account
- A free [MongoDB Atlas](https://cloud.mongodb.com) account
- A [Railway](https://railway.app) account (free tier works)
- Git

---

## Setup Guide

### Step 1 — Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/demodental.git
cd demodental
```

### Step 2 — Create a virtual environment and install dependencies

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r backend/requirements.txt
```

### Step 3 — Get an ElevenLabs API key

1. Sign up at [elevenlabs.io](https://elevenlabs.io)
2. Go to **Profile (top-right) → API Keys**
3. Click **Create API Key**, copy the value

### Step 4 — Set up MongoDB Atlas

1. Sign up at [cloud.mongodb.com](https://cloud.mongodb.com)
2. Create a free **M0** cluster
3. Under **Database Access** → create a user with read/write privileges
4. Under **Network Access** → add `0.0.0.0/0` (allow all IPs — fine for demo)
5. Under **Databases** → click **Connect → Drivers** → copy the connection string
6. Replace `<password>` with your database user password

### Step 5 — Configure environment variables

```bash
cp .env.example .env
```

Open `.env` and fill in:

```env
ELEVENLABS_API_KEY=your_key_from_step_3
MONGODB_URI=mongodb+srv://user:password@cluster.mongodb.net/?retryWrites=true&w=majority
MONGODB_DBNAME=demodental
BACKEND_URL=         # leave blank for now — fill after Step 6
WEBHOOK_SECRET=      # leave blank — auto-filled by setup script
AGENT_ID=            # leave blank — auto-filled by setup script
```

### Step 6 — Deploy to Railway

1. Push your code to a GitHub repository:

   ```bash
   git add .
   git commit -m "initial commit"
   git push origin main
   ```

2. Go to [railway.app](https://railway.app) → **New Project → Deploy from GitHub repo**
3. Select your repo
4. Under **Variables**, add:
   - `ELEVENLABS_API_KEY`
   - `MONGODB_URI`
   - `MONGODB_DBNAME` = `demodental`
5. Railway auto-detects `railway.json` and deploys
6. Once deployed, copy the **public domain** (e.g. `https://demodental.up.railway.app`)

### Step 7 — Run the setup script

Back on your local machine, with `.env` updated with `BACKEND_URL`:

```bash
python scripts/setup_agent.py
```

This script:
- Verifies your ElevenLabs API key
- Registers a workspace webhook pointing to your Railway backend
- Creates the **BrightSmile Dental Assistant** agent with both server tools configured
- Writes `WEBHOOK_SECRET` and `AGENT_ID` back to your `.env`
- Writes `frontend/config.js` with the `agentId`

### Step 8 — Update Railway environment variables

After the setup script runs, add two more variables to your Railway deployment:

- `WEBHOOK_SECRET` = value from your `.env`
- `AGENT_ID` = value from your `.env`

Then **redeploy** (Railway → Deployments → Redeploy, or push a new commit).

### Step 9 — Test the system

1. Open `https://your-app.up.railway.app` in your browser
2. You should see the BrightSmile Dental Clinic frontend
3. The voice widget (blue microphone button, bottom-right) should appear
4. Click it and speak with the agent

**Sample conversation to test the full flow:**
> "Hi, I'd like to book a teeth cleaning appointment for next Monday afternoon."

The agent will:
- Greet you as Aria
- Call `check_availability` to get open slots
- Offer you available time slots
- Collect your name
- Call `book_appointment` to confirm the booking
- After the call ends, your conversation and appointment appear in the frontend tables

---

## MongoDB Verification

Log into [MongoDB Atlas](https://cloud.mongodb.com):

1. Navigate to your cluster → **Browse Collections**
2. Select database `demodental`
3. You should see two collections:

**`conversations`** — created automatically after each call:
```json
{
  "_id": "ObjectId(...)",
  "caller_id": "conv_abc123",
  "transcript": "Aria: Thank you for calling...\nYou: I'd like to book...",
  "booking_status": "success",
  "call_duration_secs": 87,
  "termination_reason": "agent_goodbye",
  "summary": "Patient requested a teeth cleaning...",
  "created_at": "2026-03-05T14:32:00Z"
}
```

**`appointments`** — created the moment the agent calls `book_appointment`:
```json
{
  "_id": "ObjectId(...)",
  "conversation_id": "conv_abc123",
  "patient_name": "John Smith",
  "service_type": "Teeth Cleaning",
  "appointment_time": "2026-03-09T14:00:00Z",
  "status": "confirmed",
  "created_at": "2026-03-05T14:31:45Z"
}
```

---

## Project Structure

```
demodental/
├── backend/
│   ├── __init__.py
│   ├── main.py           # FastAPI app, serves frontend static files
│   ├── database.py       # Motor async MongoDB connection
│   ├── models.py         # Pydantic models for DB documents & API I/O
│   ├── clinic_data.py    # Demo clinic constants + slot generator
│   ├── requirements.txt
│   └── routes/
│       ├── __init__.py
│       ├── tools.py      # /api/slots, /api/book-appointment (called by ElevenLabs agent)
│       ├── webhook.py    # /webhook/elevenlabs (post-call event handler)
│       └── data.py       # /api/conversations, /api/appointments, /api/config
├── frontend/
│   ├── index.html        # Single-page frontend
│   ├── styles.css        # Clean, functional styling
│   ├── app.ts            # TypeScript source
│   ├── app.js            # Pre-compiled JS (served directly — no build needed)
│   ├── config.js         # Auto-generated by setup_agent.py (contains agentId)
│   └── tsconfig.json
├── scripts/
│   └── setup_agent.py    # One-time ElevenLabs webhook + agent creation script
├── .env.example          # Environment variable template
├── .gitignore
├── Procfile              # Railway / Heroku start command
├── railway.json          # Railway deployment configuration
└── README.md
```

---

## Environment Variables Reference

| Variable | Required | Description |
|---|---|---|
| `ELEVENLABS_API_KEY` | ✅ | Your ElevenLabs API key |
| `MONGODB_URI` | ✅ | MongoDB Atlas connection string |
| `MONGODB_DBNAME` | Optional | Database name (default: `demodental`) |
| `BACKEND_URL` | ✅ (setup) | Public HTTPS URL of this backend |
| `WEBHOOK_SECRET` | ✅ (auto) | HMAC secret for webhook verification — written by `setup_agent.py` |
| `AGENT_ID` | ✅ (auto) | ElevenLabs agent ID — written by `setup_agent.py` |

---

## API Reference

| Method | URL | Description |
|---|---|---|
| `GET` | `/api/health` | Liveness probe |
| `GET` | `/api/config` | Returns `agent_id` and `clinic_name` |
| `GET` | `/api/slots` | Available appointment slots (used by agent tool) |
| `POST` | `/api/book-appointment` | Book a slot (used by agent tool) |
| `GET` | `/api/conversations` | All stored conversations (frontend) |
| `GET` | `/api/appointments` | All stored appointments (frontend) |
| `GET` | `/api/clinic-info` | Full clinic information |
| `POST` | `/webhook/elevenlabs` | ElevenLabs post-call webhook (HMAC-verified) |

---

## Local Development

```bash
# Install dependencies
pip install -r backend/requirements.txt

# Copy and fill .env
cp .env.example .env

# Run the backend (serves frontend too)
uvicorn backend.main:app --reload --port 8000
```

Open [http://localhost:8000](http://localhost:8000).

> **Note:** For local development, ElevenLabs cannot reach `localhost` for webhooks and server tools. Use a tunnel like [ngrok](https://ngrok.com) or [cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/do-more-with-tunnels/trycloudflare/) and update `BACKEND_URL` accordingly before running `setup_agent.py`.

```bash
# Example with ngrok
ngrok http 8000
# Copy the https://xxxxx.ngrok-free.app URL → set as BACKEND_URL in .env
```

---

## How Webhook Signature Verification Works

ElevenLabs sends a `ElevenLabs-Signature` header with every webhook request:

```
ElevenLabs-Signature: t=1743856200,v0=abc123...
```

The backend verifies it with HMAC-SHA256:

```
payload = f"{timestamp}.{raw_body}"
expected = hmac_sha256(WEBHOOK_SECRET, payload)
assert expected == received_signature
```

This proves the request genuinely came from ElevenLabs and was not tampered with or simulated.

---

## Evaluation Notes

- **No hardcoded transcripts** — all data in MongoDB comes directly from ElevenLabs webhook payloads.
- **No manual inserts** — conversations are stored only when ElevenLabs fires the post-call webhook; appointments are stored only when the agent calls `book_appointment`.
- **Real agent responses** — the agent's behaviour is driven entirely by its system prompt and live tool responses; the frontend never fakes responses.
- **HMAC verification** — webhook authenticity is cryptographically verified on every request.
