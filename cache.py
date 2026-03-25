"""Audio cache layer for Kokoro TTS — caches synthesis results and serves as a snippet library."""

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path

from bson import ObjectId

CACHE_DIR = Path(os.environ.get("AUDIO_CACHE_DIR", "/app/audio_cache"))

# Default cache settings — overridden by MongoDB settings collection
DEFAULT_SETTINGS = {
    "enabled": True,
    "min_text_length": 10,       # don't cache very short texts like "ok", "yes"
    "max_text_length": 5000,     # skip caching extremely long texts
    "max_audio_duration": 120,   # seconds — skip caching very long generations
    "max_file_size_mb": 50,      # per-entry WAV size limit in MB
    "max_total_size_mb": 1024,   # overall cache disk usage cap (1 GB)
    "max_entries": 5000,         # cap on total cached items
    "ttl_days": 30,              # auto-expire entries not accessed in N days (0 = never)
}

# In-memory settings cache (refreshed from MongoDB)
_settings: dict = dict(DEFAULT_SETTINGS)


async def get_settings() -> dict:
    """Return current cache settings (from memory)."""
    return dict(_settings)


async def load_settings():
    """Load cache settings from MongoDB into memory."""
    from db import settings, get_db
    if get_db() is None:
        return
    doc = await settings().find_one({"_id": "cache"})
    if doc:
        for key in DEFAULT_SETTINGS:
            if key in doc:
                _settings[key] = doc[key]


async def save_settings(updates: dict) -> dict:
    """Save cache settings to MongoDB and update memory."""
    from db import settings, get_db
    if get_db() is None:
        return dict(_settings)
    # Only accept known keys
    valid = {k: v for k, v in updates.items() if k in DEFAULT_SETTINGS}
    _settings.update(valid)
    await settings().update_one(
        {"_id": "cache"},
        {"$set": valid},
        upsert=True,
    )
    return dict(_settings)


async def should_cache(text: str, wav_bytes: bytes | None = None, duration: float | None = None) -> bool:
    """Check if this generation should be cached based on current settings."""
    if not _settings["enabled"]:
        return False
    if len(text) < _settings["min_text_length"]:
        return False
    if len(text) > _settings["max_text_length"]:
        return False
    if duration is not None and duration > _settings["max_audio_duration"]:
        return False
    if wav_bytes is not None and len(wav_bytes) > _settings["max_file_size_mb"] * 1024 * 1024:
        return False
    from db import cache as cache_coll, get_db
    if get_db() is None:
        return True
    # Check total entry count
    if _settings["max_entries"] > 0:
        count = await cache_coll().count_documents({})
        if count >= _settings["max_entries"]:
            return False
    # Check total cache size on disk
    if _settings["max_total_size_mb"] > 0:
        pipeline = [{"$group": {"_id": None, "total": {"$sum": "$file_size_bytes"}}}]
        result = await cache_coll().aggregate(pipeline).to_list(1)
        total_bytes = result[0]["total"] if result else 0
        if total_bytes >= _settings["max_total_size_mb"] * 1024 * 1024:
            return False
    return True


async def enforce_ttl():
    """Remove cache entries that haven't been accessed within TTL days."""
    from db import cache as cache_coll, get_db
    if get_db() is None or _settings["ttl_days"] <= 0:
        return 0
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=_settings["ttl_days"])
    expired = cache_coll().find({"last_accessed_at": {"$lt": cutoff}})
    removed = 0
    async for doc in expired:
        file_path = CACHE_DIR / doc["file_path"]
        if file_path.exists():
            file_path.unlink()
        await cache_coll().delete_one({"_id": doc["_id"]})
        removed += 1
    return removed


def compute_cache_key(text: str, voice: str, speed: float, lang_code: str = "a") -> str:
    """SHA-256 hash of normalized (text, voice, speed, lang_code) tuple."""
    canonical = f"{text}|{voice}|{speed:.1f}|{lang_code}"
    return hashlib.sha256(canonical.encode()).hexdigest()


async def lookup(text: str, voice: str, speed: float, lang_code: str = "a"):
    """Check cache for matching audio. Returns (cache_doc, file_path) or (None, None)."""
    from db import cache, get_db
    if get_db() is None:
        return None, None
    key = compute_cache_key(text, voice, speed, lang_code)
    doc = await cache().find_one({"cache_key": key})
    if doc:
        full_path = CACHE_DIR / doc["file_path"]
        if full_path.exists():
            # Increment hit count
            await cache().update_one(
                {"_id": doc["_id"]},
                {"$inc": {"hit_count": 1}, "$set": {"last_accessed_at": datetime.now(timezone.utc)}},
            )
            return doc, full_path
        # File missing on disk — remove stale entry
        await cache().delete_one({"_id": doc["_id"]})
    return None, None


async def store(text: str, voice: str, speed: float, wav_bytes: bytes, duration: float, sample_rate: int, lang_code: str = "a"):
    """Store audio in cache. Returns the cache document or None if skipped/failed."""
    from db import cache, get_db
    if get_db() is None:
        return None
    if not await should_cache(text, wav_bytes=wav_bytes, duration=duration):
        return None
    key = compute_cache_key(text, voice, speed, lang_code)
    shard = key[:2]
    rel_path = f"{shard}/{key}.wav"
    full_path = CACHE_DIR / rel_path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_bytes(wav_bytes)
    now = datetime.now(timezone.utc)
    doc = {
        "cache_key": key,
        "text": text,
        "voice": voice,
        "speed": speed,
        "lang_code": lang_code,
        "audio_duration_sec": duration,
        "sample_rate": sample_rate,
        "file_path": rel_path,
        "file_size_bytes": len(wav_bytes),
        "tags": [],
        "label": None,
        "hit_count": 0,
        "created_at": now,
        "last_accessed_at": now,
    }
    try:
        result = await cache().insert_one(doc)
        doc["_id"] = result.inserted_id
        return doc
    except Exception:
        # Duplicate key (race condition) — return existing
        existing = await cache().find_one({"cache_key": key})
        return existing


async def list_entries(search: str = "", tag: str = "", skip: int = 0, limit: int = 50):
    """List cache entries with optional text search and tag filter."""
    from db import cache, get_db
    if get_db() is None:
        return [], 0
    query = {}
    if search:
        query["$text"] = {"$search": search}
    if tag:
        query["tags"] = tag
    cursor = cache().find(query).sort("created_at", -1).skip(skip).limit(limit)
    docs = await cursor.to_list(length=limit)
    total = await cache().count_documents(query)
    # Convert ObjectId and datetime for JSON
    for doc in docs:
        doc["_id"] = str(doc["_id"])
        if "created_at" in doc:
            doc["created_at"] = doc["created_at"].isoformat()
        if "last_accessed_at" in doc:
            doc["last_accessed_at"] = doc["last_accessed_at"].isoformat()
    return docs, total


async def get_entry(cache_id: str):
    """Get a single cache entry by ID."""
    from db import cache, get_db
    if get_db() is None:
        return None
    try:
        doc = await cache().find_one({"_id": ObjectId(cache_id)})
    except Exception:
        return None
    if doc:
        doc["_id"] = str(doc["_id"])
        if "created_at" in doc:
            doc["created_at"] = doc["created_at"].isoformat()
        if "last_accessed_at" in doc:
            doc["last_accessed_at"] = doc["last_accessed_at"].isoformat()
    return doc


async def update_tags(cache_id: str, tags: list[str] | None = None, label: str | None = None):
    """Update tags and/or label on a cache entry."""
    from db import cache, get_db
    if get_db() is None:
        return None
    update = {}
    if tags is not None:
        update["tags"] = tags
    if label is not None:
        update["label"] = label
    if not update:
        return await get_entry(cache_id)
    try:
        await cache().update_one({"_id": ObjectId(cache_id)}, {"$set": update})
    except Exception:
        return None
    return await get_entry(cache_id)


async def delete_entry(cache_id: str) -> bool:
    """Remove a cache entry and its audio file. Returns True if deleted."""
    from db import cache, get_db
    if get_db() is None:
        return False
    try:
        doc = await cache().find_one({"_id": ObjectId(cache_id)})
    except Exception:
        return False
    if not doc:
        return False
    # Delete file from disk
    file_path = CACHE_DIR / doc["file_path"]
    if file_path.exists():
        file_path.unlink()
    await cache().delete_one({"_id": doc["_id"]})
    return True
