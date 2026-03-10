"""
Async MongoDB connection using Motor.
Collections are created automatically on first use (Atlas free tier is fine).
"""
from __future__ import annotations

import os
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

_client: Optional[AsyncIOMotorClient] = None
_db: Optional[AsyncIOMotorDatabase] = None


def _get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        uri = os.environ["MONGODB_URI"]
        _client = AsyncIOMotorClient(
            uri,
            # Wait long enough for Atlas M0 to wake from idle (~30s reconnect time)
            serverSelectionTimeoutMS=35000,
            connectTimeoutMS=35000,
            socketTimeoutMS=40000,
            # Keep the connection alive with regular heartbeats
            heartbeatFrequencyMS=10000,
        )
    return _client


def get_db() -> AsyncIOMotorDatabase:
    global _db
    if _db is None:
        client = _get_client()
        db_name = os.environ.get("MONGODB_DBNAME", "demodental")
        _db = client[db_name]
    return _db


async def close_db() -> None:
    global _client, _db
    if _client is not None:
        _client.close()
        _client = None
        _db = None


# ─── Collection helpers ────────────────────────────────────────────────────────

def conversations_collection():
    return get_db()["conversations"]


def appointments_collection():
    return get_db()["appointments"]
