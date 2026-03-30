"""MongoDB persistence operations — fire-and-forget safe."""

from datetime import datetime, timezone

from src.db.connection import get_db, generations, logs


def serialize_dates(doc: dict, fields: tuple[str, ...]) -> None:
    """Convert datetime fields to ISO strings for JSON serialization."""
    for field in fields:
        if doc.get(field):
            doc[field] = doc[field].isoformat()


async def persist_log(request_id: str | None, event: str, **kwargs):
    """Write a full log entry to MongoDB (fire-and-forget safe)."""
    if get_db() is None:
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
    lang_code: str = "a",
):
    """Write a generation record to MongoDB."""
    if get_db() is None:
        return
    try:
        doc = {
            "request_id": request_id,
            "text": text,
            "voice": voice,
            "speed": speed,
            "lang_code": lang_code,
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
