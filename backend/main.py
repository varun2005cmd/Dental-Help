"""
FastAPI application entry point.

Serves:
  - Backend API routes: /api/* and /webhook/*
  - Static frontend files from ./frontend/ (index.html, styles.css, app.js)
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# Load .env before anything else (no-op in production where env vars are set directly)
load_dotenv()

from backend.database import close_db
from backend.routes import data, tools, webhook

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("BrightSmile Dental backend starting…")
    yield
    await close_db()
    logger.info("BrightSmile Dental backend shut down.")


app = FastAPI(
    title="BrightSmile Dental Clinic API",
    description="Demo dental clinic voice booking backend powered by ElevenLabs + MongoDB.",
    version="1.0.0",
    lifespan=lifespan,
)

# ── CORS ──────────────────────────────────────────────────────────────────────
# Allow all origins for this demo system (restrict in production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── API Routes ────────────────────────────────────────────────────────────────
app.include_router(data.router)
app.include_router(tools.router)
app.include_router(webhook.router)

# ── Serve Frontend ────────────────────────────────────────────────────────────
# The frontend directory must exist; Railway's build step handles this.
_frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.isdir(_frontend_dir):
    app.mount("/", StaticFiles(directory=_frontend_dir, html=True), name="frontend")
    logger.info("Serving frontend from %s", _frontend_dir)
else:
    logger.warning("Frontend directory not found at %s — static serving disabled", _frontend_dir)
