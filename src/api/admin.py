"""Admin and monitoring endpoints — stats, health, voices, settings, logs, generations."""

import os
import sys
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from src.cache import manager as audio_cache
from src.core import state
from src.core.logging import ws_clients
from src.db import generations, get_db, logs, serialize_dates, settings
from src.tts import LANGUAGE_CODES, KokoroTTS

router = APIRouter()

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


@router.get("/", include_in_schema=False)
async def root():
    return FileResponse(_PROJECT_ROOT / "static" / "index.html")


@router.websocket("/ws/logs")
async def websocket_logs(ws: WebSocket):
    await ws.accept()
    ws_clients.add(ws)
    try:
        while True:
            await ws.receive_text()  # keep alive, ignore client messages
    except WebSocketDisconnect:
        pass
    finally:
        ws_clients.discard(ws)


@router.get("/stats")
async def stats():
    """System, process, and TTS metrics for the dashboard."""
    import torch

    mem = state.read_proc_meminfo()
    proc = state.read_process_mem()
    cpu = state.read_cpu_percent()
    uptime = time.time() - state.start_time

    return {
        "system": {
            "cpu_count": os.cpu_count(),
            "cpu_percent": cpu,
            "mem_total": mem.get("MemTotal", 0),
            "mem_available": mem.get("MemAvailable", 0),
            "mem_used": mem.get("MemTotal", 0) - mem.get("MemAvailable", 0),
        },
        "process": {
            "rss": proc.get("VmRSS", 0),
            "peak_rss": proc.get("VmPeak", 0),
            "virtual": proc.get("VmSize", 0),
        },
        "model": {
            "name": "Kokoro-82M",
            "params": "82M",
            "loaded": state.tts is not None and state.tts.is_loaded,
            "device": "cuda" if torch.cuda.is_available() else "cpu",
            "torch_version": torch.__version__,
        },
        "tts": {
            "total_requests": state.req_count,
            "total_audio_seconds": round(state.total_audio_sec, 2),
            "total_synth_ms": round(state.total_synth_ms, 1),
            "avg_synth_ms": round(state.total_synth_ms / state.req_count, 1) if state.req_count > 0 else 0,
            "requests_per_minute": round(state.req_count / (uptime / 60), 2) if uptime > 0 else 0,
        },
        "server": {
            "uptime_seconds": round(uptime, 1),
            "python_version": sys.version.split()[0],
        },
    }


@router.get("/health")
async def health():
    if state.tts is None or not state.tts.is_loaded:
        raise HTTPException(status_code=503, detail="Model not loaded")
    return {
        "status": "ready",
        "model": "Kokoro-82M",
        "uptime_seconds": round(time.time() - state.start_time, 1),
    }


@router.get("/voices")
async def voices():
    return {"voices": [{"id": vid, "name": name} for vid, name in KokoroTTS.list_voices().items()]}


@router.get("/languages")
async def languages():
    return {"languages": [{"code": code, "name": name} for code, name in LANGUAGE_CODES.items()]}


@router.get("/settings/cache")
async def get_cache_settings():
    """Get current cache settings."""

    return await audio_cache.get_settings()


@router.put("/settings/cache")
async def update_cache_settings(req: Request):
    """Update cache settings."""

    body = await req.json()
    updated = await audio_cache.save_settings(body)
    return updated


@router.post("/settings/cache/ttl-cleanup")
async def run_ttl_cleanup():
    """Manually trigger TTL cleanup of expired cache entries."""

    removed = await audio_cache.enforce_ttl()
    return {"removed": removed}


_LOG_SETTINGS_DEFAULTS = {"refresh_interval_sec": 5}


@router.get("/settings/logs")
async def get_log_settings():
    """Get log UI settings."""
    result = dict(_LOG_SETTINGS_DEFAULTS)
    if get_db() is not None:
        doc = await settings().find_one({"_id": "logs"})
        if doc:
            for k in _LOG_SETTINGS_DEFAULTS:
                if k in doc:
                    result[k] = doc[k]
    return result


@router.put("/settings/logs")
async def update_log_settings(req: Request):
    """Update log UI settings."""
    if get_db() is None:
        raise HTTPException(status_code=503, detail="MongoDB unavailable")
    body = await req.json()
    valid = {k: v for k, v in body.items() if k in _LOG_SETTINGS_DEFAULTS}
    await settings().update_one({"_id": "logs"}, {"$set": valid}, upsert=True)
    return await get_log_settings()


@router.get("/logs")
async def list_logs(
    skip: int = 0,
    limit: int = 50,
    event: str = "",
    request_id: str = "",
    search: str = "",
):
    """List logs from MongoDB with filtering and pagination."""
    if get_db() is None:
        return {"logs": [], "total": 0}
    query = {}
    if event:
        query["event"] = event
    if request_id:
        query["request_id"] = request_id
    if search:
        # Search in data fields — match text content
        query["$or"] = [
            {"data.text": {"$regex": search, "$options": "i"}},
            {"data.path": {"$regex": search, "$options": "i"}},
            {"data.error": {"$regex": search, "$options": "i"}},
            {"request_id": {"$regex": search, "$options": "i"}},
        ]
    cursor = logs().find(query, {"_id": 0}).sort("created_at", -1).skip(skip).limit(limit)
    docs = await cursor.to_list(length=limit)
    total = await logs().count_documents(query)
    for doc in docs:
        serialize_dates(doc, ("created_at",))
    return {"logs": docs, "total": total}


@router.get("/logs/events")
async def list_log_events():
    """List distinct event types in the logs collection."""
    if get_db() is None:
        return {"events": []}
    events = await logs().distinct("event")
    return {"events": sorted(events)}


@router.get("/generations")
async def list_generations(skip: int = 0, limit: int = 50):
    """List generation history from MongoDB."""
    if get_db() is None:
        return {"generations": [], "total": 0}
    cursor = generations().find({}, {"_id": 0}).sort("created_at", -1).skip(skip).limit(limit)
    docs = await cursor.to_list(length=limit)
    total = await generations().count_documents({})
    for doc in docs:
        serialize_dates(doc, ("created_at",))
    return {"generations": docs, "total": total}
