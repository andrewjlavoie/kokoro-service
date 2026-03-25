"""Kokoro TTS FastAPI server — keeps the model hot in memory."""

import asyncio
import io
import json
import logging
import os
import struct
import sys
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from kokoro_sdk import SAMPLE_RATE, KokoroTTS

# ---------------------------------------------------------------------------
# Structured JSON logging + WebSocket broadcast
# ---------------------------------------------------------------------------
logger = logging.getLogger("kokoro-server")
logger.setLevel(logging.INFO)

# Stdout handler
_stdout_handler = logging.StreamHandler(sys.stdout)
_stdout_handler.setFormatter(logging.Formatter(
    '{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":%(message)s}'
))
logger.addHandler(_stdout_handler)

# Suppress noisy torch/hf warnings from cluttering logs
logging.getLogger("torch").setLevel(logging.ERROR)
logging.getLogger("huggingface_hub").setLevel(logging.WARNING)

# WebSocket broadcast set
_ws_clients: set[WebSocket] = set()


class WebSocketLogHandler(logging.Handler):
    """Broadcasts log records to all connected WebSocket clients."""

    def emit(self, record):
        try:
            raw = record.getMessage()
            # Try to parse our structured JSON messages
            try:
                msg = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                msg = raw.strip('"')
            entry = json.dumps({
                "time": self.format(record).split(",")[0] if hasattr(record, "asctime") else time.strftime("%H:%M:%S"),
                "level": record.levelname,
                "message": msg,
            })
            for ws in list(_ws_clients):
                asyncio.create_task(_ws_send(ws, entry))
        except Exception:
            pass


async def _ws_send(ws: WebSocket, data: str):
    try:
        await ws.send_text(data)
    except Exception:
        _ws_clients.discard(ws)


_ws_handler = WebSocketLogHandler()
_ws_handler.setFormatter(logging.Formatter("%(asctime)s"))
logger.addHandler(_ws_handler)


def _log_json(request_id: str, event: str, **kwargs):
    """Log a structured JSON event with consistent format."""
    parts = [f'"request_id":"{request_id}"', f'"event":"{event}"']
    for k, v in kwargs.items():
        if isinstance(v, str):
            # Escape quotes and backslashes in string values
            escaped = v.replace("\\", "\\\\").replace('"', '\\"')
            parts.append(f'"{k}":"{escaped}"')
        else:
            parts.append(f'"{k}":{v}')
    logger.info("{" + ",".join(parts) + "}")


async def _persist_log(request_id: str, event: str, **kwargs):
    """Write full log entry to MongoDB (fire-and-forget)."""
    from db import persist_log
    await persist_log(request_id, event, **kwargs)


async def _persist_generation(**kwargs):
    """Write generation record to MongoDB (fire-and-forget)."""
    from db import persist_generation
    await persist_generation(**kwargs)

# ---------------------------------------------------------------------------
# App state + request tracking
# ---------------------------------------------------------------------------
_start_time: float = 0
tts: KokoroTTS | None = None
_req_count: int = 0
_total_audio_sec: float = 0
_total_synth_ms: float = 0
_last_cpu_sample: tuple = (0.0, 0.0)  # (busy, total) from /proc/stat


def _read_proc_meminfo() -> dict:
    """Read system memory from /proc/meminfo."""
    info = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                parts = line.split()
                if parts[0].rstrip(":") in ("MemTotal", "MemAvailable", "MemFree"):
                    info[parts[0].rstrip(":")] = int(parts[1]) * 1024  # kB -> bytes
    except OSError:
        pass
    return info


def _read_process_mem() -> dict:
    """Read process memory from /proc/self/status."""
    info = {}
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith(("VmRSS", "VmPeak", "VmSize")):
                    parts = line.split()
                    info[parts[0].rstrip(":")] = int(parts[1]) * 1024  # kB -> bytes
    except OSError:
        pass
    return info


def _read_cpu_percent() -> float:
    """Estimate CPU usage % since last sample from /proc/stat."""
    global _last_cpu_sample
    try:
        with open("/proc/stat") as f:
            fields = f.readline().split()[1:]  # skip 'cpu' label
        vals = [int(v) for v in fields]
        idle = vals[3] + (vals[4] if len(vals) > 4 else 0)  # idle + iowait
        total = sum(vals)
        prev_busy, prev_total = _last_cpu_sample
        d_total = total - prev_total
        d_busy = (total - idle) - prev_busy
        _last_cpu_sample = (total - idle, total)
        if d_total == 0:
            return 0.0
        return round(d_busy / d_total * 100, 1)
    except OSError:
        return 0.0


@asynccontextmanager
async def lifespan(app: FastAPI):
    global tts, _start_time
    _start_time = time.time()
    # Initialize MongoDB (graceful — server works without it)
    try:
        from db import init_db
        await init_db()
        logger.info('"MongoDB connected"')
        # Load cache settings from MongoDB
        import cache as audio_cache
        await audio_cache.load_settings()
    except Exception as e:
        logger.warning(f'"MongoDB unavailable: {e} — running without persistence"')
    # Load TTS model
    logger.info('"Loading Kokoro-82M model..."')
    t0 = time.monotonic()
    tts = KokoroTTS()
    tts._ensure_pipeline()  # force model load at startup
    elapsed = time.monotonic() - t0
    logger.info(f'"Model loaded in {elapsed:.1f}s"')
    yield
    from db import close_db
    await close_db()
    logger.info('"Server shutting down"')


app = FastAPI(title="Kokoro TTS", version="0.2.0", lifespan=lifespan)

# ---------------------------------------------------------------------------
# Request logging middleware
# ---------------------------------------------------------------------------

@app.middleware("http")
async def log_requests(request: Request, call_next):
    # Skip logging for static files, websocket, health checks, and voice list
    skip = request.url.path.startswith("/static") or request.url.path in ("/ws/logs", "/health", "/stats", "/voices", "/", "/generations")
    request_id = str(uuid.uuid4())[:8]
    request.state.request_id = request_id
    t0 = time.monotonic()
    response = await call_next(request)
    if not skip:
        elapsed_ms = (time.monotonic() - t0) * 1000
        logger.info(
            f'{{"request_id":"{request_id}",'
            f'"method":"{request.method}",'
            f'"path":"{request.url.path}",'
            f'"status":{response.status_code},'
            f'"duration_ms":{elapsed_ms:.1f}}}'
        )
    response.headers["X-Request-ID"] = request_id
    return response


# ---------------------------------------------------------------------------
# Request/response models
# ---------------------------------------------------------------------------

class SpeechRequest(BaseModel):
    input: str = Field(..., min_length=1, max_length=10000)
    voice: str = "af_heart"
    speed: float = 1.0


class BatchItem(BaseModel):
    input: str = Field(..., min_length=1, max_length=10000)
    voice: str = "af_heart"
    speed: float = 1.0


class BatchRequest(BaseModel):
    items: list[BatchItem] = Field(..., min_length=1, max_length=100)


# ---------------------------------------------------------------------------
# WAV helpers
# ---------------------------------------------------------------------------

def wav_header(sample_rate: int, num_channels: int = 1, bits_per_sample: int = 16, data_size: int = 0xFFFFFFFF) -> bytes:
    """Build a WAV header. Use data_size=0xFFFFFFFF for streaming (unknown length)."""
    byte_rate = sample_rate * num_channels * bits_per_sample // 8
    block_align = num_channels * bits_per_sample // 8
    riff_size = data_size + 36 if data_size != 0xFFFFFFFF else 0xFFFFFFFF
    return struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", riff_size, b"WAVE",
        b"fmt ", 16, 1, num_channels,
        sample_rate, byte_rate, block_align, bits_per_sample,
        b"data", data_size,
    )


def audio_to_pcm16(audio) -> bytes:
    """Convert float32 numpy array to 16-bit PCM bytes."""
    import numpy as np
    pcm = (audio * 32767).clip(-32768, 32767).astype(np.int16)
    return pcm.tobytes()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
async def root():
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.websocket("/ws/logs")
async def websocket_logs(ws: WebSocket):
    await ws.accept()
    _ws_clients.add(ws)
    try:
        while True:
            await ws.receive_text()  # keep alive, ignore client messages
    except WebSocketDisconnect:
        pass
    finally:
        _ws_clients.discard(ws)


@app.get("/stats")
async def stats():
    """System, process, and TTS metrics for the dashboard."""
    import torch
    mem = _read_proc_meminfo()
    proc = _read_process_mem()
    cpu = _read_cpu_percent()
    uptime = time.time() - _start_time

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
            "loaded": tts is not None and tts._pipeline is not None,
            "device": "cuda" if torch.cuda.is_available() else "cpu",
            "torch_version": torch.__version__,
        },
        "tts": {
            "total_requests": _req_count,
            "total_audio_seconds": round(_total_audio_sec, 2),
            "total_synth_ms": round(_total_synth_ms, 1),
            "avg_synth_ms": round(_total_synth_ms / _req_count, 1) if _req_count > 0 else 0,
            "requests_per_minute": round(_req_count / (uptime / 60), 2) if uptime > 0 else 0,
        },
        "server": {
            "uptime_seconds": round(uptime, 1),
            "python_version": sys.version.split()[0],
        },
    }


@app.get("/health")
async def health():
    if tts is None or tts._pipeline is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    return {
        "status": "ready",
        "model": "Kokoro-82M",
        "uptime_seconds": round(time.time() - _start_time, 1),
    }


@app.get("/voices")
async def voices():
    return {
        "voices": [
            {"id": vid, "name": name}
            for vid, name in KokoroTTS.list_voices().items()
        ]
    }


@app.post("/v1/audio/speech")
async def speech_stream(req: SpeechRequest):
    """OpenAI-compatible TTS endpoint with streaming audio."""
    if tts is None:
        raise HTTPException(status_code=503, detail="Model not loaded")

    request_id = str(uuid.uuid4())[:8]

    # Check cache — return full WAV immediately on hit
    import cache as audio_cache
    cache_doc, cache_path = await audio_cache.lookup(req.input, req.voice, req.speed)
    if cache_doc and cache_path:
        _log_json(request_id, "cache_hit", text=req.input, voice=req.voice, cache_key=cache_doc["cache_key"][:12])
        asyncio.create_task(_persist_log(request_id, "cache_hit", text=req.input, voice=req.voice, speed=req.speed))
        asyncio.create_task(_persist_generation(
            request_id=request_id, text=req.input, voice=req.voice, speed=req.speed,
            audio_duration_sec=cache_doc["audio_duration_sec"], synth_time_ms=0,
            sample_rate=cache_doc["sample_rate"], audio_size_bytes=cache_doc["file_size_bytes"],
            endpoint="/v1/audio/speech", cache_hit=True, cache_id=str(cache_doc["_id"]),
        ))
        global _req_count, _total_audio_sec, _total_synth_ms
        _req_count += 1
        _total_audio_sec += cache_doc["audio_duration_sec"]
        wav_bytes = cache_path.read_bytes()
        return Response(content=wav_bytes, media_type="audio/wav", headers={
            "X-Request-ID": request_id,
            "X-Cache": "hit",
        })

    _log_json(request_id, "stream_start", text=req.input, voice=req.voice, speed=req.speed, chars=len(req.input))
    asyncio.create_task(_persist_log(request_id, "stream_start", text=req.input, voice=req.voice, speed=req.speed, chars=len(req.input)))

    # Collect all PCM for caching after stream completes
    _pcm_chunks = []

    def generate():
        t0 = time.monotonic()
        total_samples = 0
        segment_count = 0
        yield wav_header(SAMPLE_RATE)
        for segment in tts.synthesize_stream(req.input, voice=req.voice, speed=req.speed):
            pcm = audio_to_pcm16(segment)
            _pcm_chunks.append(pcm)
            total_samples += len(segment)
            segment_count += 1
            seg_dur = len(segment) / SAMPLE_RATE
            _log_json(request_id, "stream_segment", segment=segment_count, segment_duration=f"{seg_dur:.2f}s")
            yield pcm
        elapsed_ms = (time.monotonic() - t0) * 1000
        duration = total_samples / SAMPLE_RATE
        _log_json(request_id, "stream_complete", audio_duration=f"{duration:.2f}s", synth_time=f"{elapsed_ms:.0f}ms", segments=segment_count)
        asyncio.create_task(_persist_log(request_id, "stream_complete", audio_duration=duration, synth_time_ms=elapsed_ms, segments=segment_count))
        asyncio.create_task(_persist_generation(
            request_id=request_id, text=req.input, voice=req.voice, speed=req.speed,
            audio_duration_sec=duration, synth_time_ms=elapsed_ms, sample_rate=SAMPLE_RATE,
            audio_size_bytes=total_samples * 2, endpoint="/v1/audio/speech",
        ))
        # Cache the complete audio
        all_pcm = b"".join(_pcm_chunks)
        pcm_size = len(all_pcm)
        full_wav = wav_header(SAMPLE_RATE, data_size=pcm_size) + all_pcm
        asyncio.create_task(audio_cache.store(req.input, req.voice, req.speed, full_wav, duration, SAMPLE_RATE))
        global _req_count, _total_audio_sec, _total_synth_ms
        _req_count += 1
        _total_audio_sec += duration
        _total_synth_ms += elapsed_ms

    return StreamingResponse(generate(), media_type="audio/wav")


@app.post("/synthesize")
async def synthesize(req: SpeechRequest):
    """Full WAV response with metadata headers."""
    if tts is None:
        raise HTTPException(status_code=503, detail="Model not loaded")

    request_id = str(uuid.uuid4())[:8]

    # Check cache first
    import cache as audio_cache
    cache_doc, cache_path = await audio_cache.lookup(req.input, req.voice, req.speed)
    if cache_doc and cache_path:
        _log_json(request_id, "cache_hit", text=req.input, voice=req.voice, cache_key=cache_doc["cache_key"][:12])
        asyncio.create_task(_persist_log(request_id, "cache_hit", text=req.input, voice=req.voice, speed=req.speed))
        asyncio.create_task(_persist_generation(
            request_id=request_id, text=req.input, voice=req.voice, speed=req.speed,
            audio_duration_sec=cache_doc["audio_duration_sec"], synth_time_ms=0,
            sample_rate=cache_doc["sample_rate"], audio_size_bytes=cache_doc["file_size_bytes"],
            endpoint="/synthesize", cache_hit=True, cache_id=str(cache_doc["_id"]),
        ))
        global _req_count, _total_audio_sec, _total_synth_ms
        _req_count += 1
        _total_audio_sec += cache_doc["audio_duration_sec"]
        wav_bytes = cache_path.read_bytes()
        return Response(
            content=wav_bytes,
            media_type="audio/wav",
            headers={
                "X-Request-ID": request_id,
                "X-Audio-Duration": f"{cache_doc['audio_duration_sec']:.2f}",
                "X-Sample-Rate": str(cache_doc["sample_rate"]),
                "X-Voice": req.voice,
                "X-Cache": "hit",
            },
        )

    _log_json(request_id, "synth_start", text=req.input, voice=req.voice, speed=req.speed, chars=len(req.input))
    asyncio.create_task(_persist_log(request_id, "synth_start", text=req.input, voice=req.voice, speed=req.speed, chars=len(req.input)))

    t0 = time.monotonic()
    audio, sr = tts.synthesize(req.input, voice=req.voice, speed=req.speed)
    elapsed_ms = (time.monotonic() - t0) * 1000

    if len(audio) == 0:
        _log_json(request_id, "synth_empty", error="No audio generated")
        raise HTTPException(status_code=400, detail="No audio generated")

    duration = len(audio) / sr
    _log_json(request_id, "synth_complete", audio_duration=f"{duration:.2f}s", synth_time=f"{elapsed_ms:.0f}ms", size=f"{len(audio)*2//1024}KB")
    asyncio.create_task(_persist_log(request_id, "synth_complete", audio_duration=duration, synth_time_ms=elapsed_ms, size_bytes=len(audio)*2))
    _req_count += 1
    _total_audio_sec += duration
    _total_synth_ms += elapsed_ms

    buf = io.BytesIO()
    import soundfile as sf_write
    sf_write.write(buf, audio, sr, format="WAV", subtype="PCM_16")
    wav_bytes = buf.getvalue()

    asyncio.create_task(_persist_generation(
        request_id=request_id, text=req.input, voice=req.voice, speed=req.speed,
        audio_duration_sec=duration, synth_time_ms=elapsed_ms, sample_rate=sr,
        audio_size_bytes=len(wav_bytes), endpoint="/synthesize",
    ))
    # Store in cache
    asyncio.create_task(audio_cache.store(req.input, req.voice, req.speed, wav_bytes, duration, sr))

    return Response(
        content=wav_bytes,
        media_type="audio/wav",
        headers={
            "X-Request-ID": request_id,
            "X-Audio-Duration": f"{duration:.2f}",
            "X-Sample-Rate": str(sr),
            "X-Voice": req.voice,
        },
    )


# ---------------------------------------------------------------------------
# Cache API (snippet library)
# ---------------------------------------------------------------------------

class TagRequest(BaseModel):
    tags: list[str] = []
    label: str | None = None


@app.get("/cache")
async def list_cache(search: str = "", tag: str = "", skip: int = 0, limit: int = 50):
    """List cached audio entries with optional search and tag filtering."""
    import cache as audio_cache
    docs, total = await audio_cache.list_entries(search=search, tag=tag, skip=skip, limit=limit)
    return {"entries": docs, "total": total}


@app.get("/cache/{cache_id}/meta")
async def get_cache_meta(cache_id: str):
    """Get metadata for a cached audio entry."""
    import cache as audio_cache
    doc = await audio_cache.get_entry(cache_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Cache entry not found")
    return doc


@app.get("/cache/{cache_id}")
async def get_cached_audio(cache_id: str):
    """Download a cached audio file."""
    import cache as audio_cache
    doc = await audio_cache.get_entry(cache_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Cache entry not found")
    file_path = audio_cache.CACHE_DIR / doc["file_path"]
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Audio file missing")
    return FileResponse(file_path, media_type="audio/wav", filename=f"{doc['voice']}_{cache_id[:8]}.wav")


@app.post("/cache/{cache_id}/tag")
async def tag_cache_entry(cache_id: str, req: TagRequest):
    """Update tags and/or label on a cache entry."""
    import cache as audio_cache
    doc = await audio_cache.update_tags(cache_id, tags=req.tags, label=req.label)
    if not doc:
        raise HTTPException(status_code=404, detail="Cache entry not found")
    return doc


@app.delete("/cache/{cache_id}")
async def delete_cache_entry(cache_id: str):
    """Remove a cached audio entry and its file."""
    import cache as audio_cache
    deleted = await audio_cache.delete_entry(cache_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Cache entry not found")
    return {"deleted": True}


# ---------------------------------------------------------------------------
# Settings API
# ---------------------------------------------------------------------------

@app.get("/settings/cache")
async def get_cache_settings():
    """Get current cache settings."""
    import cache as audio_cache
    return await audio_cache.get_settings()


@app.put("/settings/cache")
async def update_cache_settings(req: Request):
    """Update cache settings."""
    import cache as audio_cache
    body = await req.json()
    updated = await audio_cache.save_settings(body)
    return updated


@app.post("/settings/cache/ttl-cleanup")
async def run_ttl_cleanup():
    """Manually trigger TTL cleanup of expired cache entries."""
    import cache as audio_cache
    removed = await audio_cache.enforce_ttl()
    return {"removed": removed}


# ---------------------------------------------------------------------------
# Batch/Queue API
# ---------------------------------------------------------------------------

async def _process_batch(job_id: str):
    """Process all items in a batch job. Runs as a background task."""
    from db import batch_jobs, get_db
    import cache as audio_cache
    if get_db() is None or tts is None:
        return
    from datetime import datetime, timezone

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
            cache_doc, cache_path = await audio_cache.lookup(item["text"], item["voice"], item["speed"])
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
            import soundfile as sf_write
            t0 = time.monotonic()
            audio, sr = await asyncio.to_thread(tts.synthesize, item["text"], voice=item["voice"], speed=item["speed"])
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
            sf_write.write(buf, audio, sr, format="WAV", subtype="PCM_16")
            wav_bytes = buf.getvalue()

            # Store in cache
            stored = await audio_cache.store(item["text"], item["voice"], item["speed"], wav_bytes, duration, sr)
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
            global _req_count, _total_audio_sec, _total_synth_ms
            _req_count += 1
            _total_audio_sec += duration
            _total_synth_ms += elapsed_ms

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
    _log_json("batch", "batch_complete", job_id=job_id, status=final_status,
              completed=final_job["completed_items"], failed=final_job["failed_items"])


@app.post("/v1/audio/batch")
async def submit_batch(req: BatchRequest):
    """Submit a batch of synthesis requests. Returns job ID immediately."""
    from db import batch_jobs, get_db
    if get_db() is None:
        raise HTTPException(status_code=503, detail="MongoDB required for batch processing")
    if tts is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    from datetime import datetime, timezone

    job_id = str(uuid.uuid4())
    items = [
        {
            "index": i,
            "text": item.input,
            "voice": item.voice,
            "speed": item.speed,
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
    _log_json("batch", "batch_submitted", job_id=job_id, total_items=len(items))
    return {"job_id": job_id, "status": "pending", "total_items": len(items)}


@app.get("/v1/audio/batch/{job_id}")
async def get_batch_status(job_id: str):
    """Check batch job status and per-item progress."""
    from db import batch_jobs, get_db
    if get_db() is None:
        raise HTTPException(status_code=503, detail="MongoDB unavailable")
    doc = await batch_jobs().find_one({"job_id": job_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Batch job not found")
    # Convert datetimes
    for field in ("created_at", "started_at", "completed_at"):
        if doc.get(field):
            doc[field] = doc[field].isoformat()
    return doc


@app.get("/v1/audio/batch")
async def list_batch_jobs(skip: int = 0, limit: int = 20):
    """List recent batch jobs."""
    from db import batch_jobs, get_db
    if get_db() is None:
        return {"jobs": [], "total": 0}
    cursor = batch_jobs().find({}, {"_id": 0, "items": 0}).sort("created_at", -1).skip(skip).limit(limit)
    docs = await cursor.to_list(length=limit)
    total = await batch_jobs().count_documents({})
    for doc in docs:
        for field in ("created_at", "started_at", "completed_at"):
            if doc.get(field):
                doc[field] = doc[field].isoformat()
    return {"jobs": docs, "total": total}


# ---------------------------------------------------------------------------
# Generation history + stats
# ---------------------------------------------------------------------------

@app.get("/generations")
async def list_generations(skip: int = 0, limit: int = 50):
    """List generation history from MongoDB."""
    from db import get_db, generations
    if get_db() is None:
        return {"generations": [], "total": 0}
    cursor = generations().find({}, {"_id": 0}).sort("created_at", -1).skip(skip).limit(limit)
    docs = await cursor.to_list(length=limit)
    total = await generations().count_documents({})
    # Convert datetime to ISO string for JSON serialization
    for doc in docs:
        if "created_at" in doc:
            doc["created_at"] = doc["created_at"].isoformat()
    return {"generations": docs, "total": total}


# Mount static files last (so explicit routes take priority)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
