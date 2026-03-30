"""Batch processing endpoints — submit, check status, and list batch jobs."""

import asyncio
import io
import time
import uuid
from datetime import datetime, timezone

import soundfile as sf
from fastapi import APIRouter, HTTPException

from src.api.models import BatchRequest
from src.cache import manager as audio_cache
from src.core import state
from src.core.logging import log_json
from src.db import get_db, batch_jobs, persist_log, persist_generation, serialize_dates

router = APIRouter()


async def _process_batch(job_id: str):
    """Process all items in a batch job. Runs as a background task."""
    if get_db() is None or state.tts is None:
        return

    await batch_jobs().update_one(
        {"job_id": job_id},
        {"$set": {"status": "processing", "started_at": datetime.now(timezone.utc)}},
    )

    job = await batch_jobs().find_one({"job_id": job_id})
    if not job:
        return

    for i, item in enumerate(job["items"]):
        try:
            # Check cache first
            lang_code = item.get("lang_code", "a")
            cache_doc, cache_path = await audio_cache.lookup(item["text"], item["voice"], item["speed"], lang_code)
            if cache_doc and cache_path:
                await batch_jobs().update_one(
                    {"job_id": job_id},
                    {"$set": {
                        f"items.{i}.status": "completed",
                        f"items.{i}.cache_id": str(cache_doc["_id"]),
                        f"items.{i}.audio_duration_sec": cache_doc["audio_duration_sec"],
                        f"items.{i}.synth_time_ms": 0,
                        f"items.{i}.cache_hit": True,
                    }, "$inc": {"completed_items": 1}},
                )
                continue

            # Synthesize (run in thread to avoid blocking event loop)
            t0 = time.monotonic()
            audio, sr = await asyncio.to_thread(state.tts.synthesize, item["text"], voice=item["voice"], speed=item["speed"], lang_code=lang_code)
            elapsed_ms = (time.monotonic() - t0) * 1000

            if len(audio) == 0:
                await batch_jobs().update_one(
                    {"job_id": job_id},
                    {"$set": {f"items.{i}.status": "failed", f"items.{i}.error": "No audio generated"},
                     "$inc": {"failed_items": 1}},
                )
                continue

            duration = len(audio) / sr
            buf = io.BytesIO()
            sf.write(buf, audio, sr, format="WAV", subtype="PCM_16")
            wav_bytes = buf.getvalue()

            # Store in cache
            stored = await audio_cache.store(item["text"], item["voice"], item["speed"], wav_bytes, duration, sr, lang_code)
            cache_id = str(stored["_id"]) if stored else None

            await batch_jobs().update_one(
                {"job_id": job_id},
                {"$set": {
                    f"items.{i}.status": "completed",
                    f"items.{i}.cache_id": cache_id,
                    f"items.{i}.audio_duration_sec": duration,
                    f"items.{i}.synth_time_ms": round(elapsed_ms, 1),
                    f"items.{i}.cache_hit": False,
                }, "$inc": {"completed_items": 1}},
            )

            # Track global stats
            state.track_request(duration, elapsed_ms)

        except Exception as e:
            await batch_jobs().update_one(
                {"job_id": job_id},
                {"$set": {f"items.{i}.status": "failed", f"items.{i}.error": str(e)},
                 "$inc": {"failed_items": 1}},
            )

    # Mark job complete
    final_job = await batch_jobs().find_one({"job_id": job_id})
    final_status = "completed" if final_job["failed_items"] == 0 else "partial"
    await batch_jobs().update_one(
        {"job_id": job_id},
        {"$set": {"status": final_status, "completed_at": datetime.now(timezone.utc)}},
    )
    log_json("batch", "batch_complete", job_id=job_id, status=final_status,
             completed=final_job["completed_items"], failed=final_job["failed_items"])


@router.post("/v1/audio/batch")
async def submit_batch(req: BatchRequest):
    """Submit a batch of synthesis requests. Returns job ID immediately."""
    if get_db() is None:
        raise HTTPException(status_code=503, detail="MongoDB required for batch processing")
    if state.tts is None:
        raise HTTPException(status_code=503, detail="Model not loaded")

    job_id = str(uuid.uuid4())
    items = [
        {
            "index": i,
            "text": item.input,
            "voice": item.voice,
            "speed": item.speed,
            "lang_code": item.lang_code,
            "status": "pending",
            "cache_id": None,
            "audio_duration_sec": None,
            "synth_time_ms": None,
            "cache_hit": False,
            "error": None,
        }
        for i, item in enumerate(req.items)
    ]
    await batch_jobs().insert_one({
        "job_id": job_id,
        "status": "pending",
        "items": items,
        "total_items": len(items),
        "completed_items": 0,
        "failed_items": 0,
        "created_at": datetime.now(timezone.utc),
        "started_at": None,
        "completed_at": None,
    })
    asyncio.create_task(_process_batch(job_id))
    log_json("batch", "batch_submitted", job_id=job_id, total_items=len(items))
    return {"job_id": job_id, "status": "pending", "total_items": len(items)}


@router.get("/v1/audio/batch/{job_id}")
async def get_batch_status(job_id: str):
    """Check batch job status and per-item progress."""
    if get_db() is None:
        raise HTTPException(status_code=503, detail="MongoDB unavailable")
    doc = await batch_jobs().find_one({"job_id": job_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Batch job not found")
    serialize_dates(doc, ("created_at", "started_at", "completed_at"))
    return doc


@router.get("/v1/audio/batch")
async def list_batch_jobs(skip: int = 0, limit: int = 20):
    """List recent batch jobs."""
    if get_db() is None:
        return {"jobs": [], "total": 0}
    cursor = batch_jobs().find({}, {"_id": 0, "items": 0}).sort("created_at", -1).skip(skip).limit(limit)
    docs = await cursor.to_list(length=limit)
    total = await batch_jobs().count_documents({})
    for doc in docs:
        serialize_dates(doc, ("created_at", "started_at", "completed_at"))
    return {"jobs": docs, "total": total}
