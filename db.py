"""MongoDB connection manager for Kokoro TTS server."""

import logging
import os
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorClient

logger = logging.getLogger("kokoro-server")

_client: AsyncIOMotorClient | None = None
_db = None


async def init_db():
    """Initialize MongoDB connection and create indexes."""
    global _client, _db
    mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    db_name = os.environ.get("MONGO_DB", "kokoro")
    _client = AsyncIOMotorClient(mongo_url, serverSelectionTimeoutMS=5000)
    # Verify connection
    await _client.admin.command("ping")
    _db = _client[db_name]
    # Create indexes
    await _db.generations.create_index("request_id", unique=True)
    await _db.generations.create_index([("created_at", -1)])
    await _db.logs.create_index([("created_at", -1)])
    await _db.logs.create_index("request_id")
    await _db.cache.create_index("cache_key", unique=True)
    await _db.cache.create_index("tags")
    await _db.cache.create_index([("text", "text")])
    await _db.batch_jobs.create_index("job_id", unique=True)
    await _db.batch_jobs.create_index([("created_at", -1)])


def get_db():
    """Return the database instance, or None if unavailable."""
    return _db


def generations():
    return _db["generations"]


def logs():
    return _db["logs"]


def cache():
    return _db["cache"]


def batch_jobs():
    return _db["batch_jobs"]


def settings():
    return _db["settings"]


async def persist_log(request_id: str | None, event: str, **kwargs):
    """Write a full log entry to MongoDB (fire-and-forget safe)."""
    if _db is None:
        return
    try:
        doc = {
            "request_id": request_id,
            "event": event,
            "level": "INFO",
            "data": kwargs,
            "created_at": datetime.now(timezone.utc),
        }
        await logs().insert_one(doc)
    except Exception:
        pass


async def persist_generation(
    request_id: str,
    text: str,
    voice: str,
    speed: float,
    audio_duration_sec: float,
    synth_time_ms: float,
    sample_rate: int,
    audio_size_bytes: int,
    endpoint: str,
    cache_hit: bool = False,
    cache_id: str | None = None,
):
    """Write a generation record to MongoDB."""
    if _db is None:
        return
    try:
        doc = {
            "request_id": request_id,
            "text": text,
            "voice": voice,
            "speed": speed,
            "char_count": len(text),
            "audio_duration_sec": audio_duration_sec,
            "synth_time_ms": synth_time_ms,
            "sample_rate": sample_rate,
            "audio_size_bytes": audio_size_bytes,
            "endpoint": endpoint,
            "cache_hit": cache_hit,
            "cache_id": cache_id,
            "created_at": datetime.now(timezone.utc),
        }
        await generations().insert_one(doc)
    except Exception:
        pass


async def close_db():
    """Close the MongoDB connection."""
    global _client, _db
    if _client:
        _client.close()
        _client = None
        _db = None
