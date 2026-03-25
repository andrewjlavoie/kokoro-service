"""Audio cache layer for Kokoro TTS — caches synthesis results and serves as a snippet library."""

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path

from bson import ObjectId

CACHE_DIR = Path(os.environ.get("AUDIO_CACHE_DIR", "/app/audio_cache"))


def compute_cache_key(text: str, voice: str, speed: float) -> str:
    """SHA-256 hash of normalized (text, voice, speed) tuple."""
    canonical = f"{text}|{voice}|{speed:.1f}"
    return hashlib.sha256(canonical.encode()).hexdigest()


async def lookup(text: str, voice: str, speed: float):
    """Check cache for matching audio. Returns (cache_doc, file_path) or (None, None)."""
    from db import cache, get_db
    if get_db() is None:
        return None, None
    key = compute_cache_key(text, voice, speed)
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


async def store(text: str, voice: str, speed: float, wav_bytes: bytes, duration: float, sample_rate: int):
    """Store audio in cache. Returns the cache document or None on failure."""
    from db import cache, get_db
    if get_db() is None:
        return None
    key = compute_cache_key(text, voice, speed)
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
