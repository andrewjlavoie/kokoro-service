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
    logger.info('"Loading Kokoro-82M model..."')
    t0 = time.monotonic()
    tts = KokoroTTS()
    tts._ensure_pipeline()  # force model load at startup
    elapsed = time.monotonic() - t0
    logger.info(f'"Model loaded in {elapsed:.1f}s"')
    yield
    logger.info('"Server shutting down"')


app = FastAPI(title="Kokoro TTS", version="0.2.0", lifespan=lifespan)

# ---------------------------------------------------------------------------
# Request logging middleware
# ---------------------------------------------------------------------------

@app.middleware("http")
async def log_requests(request: Request, call_next):
    # Skip logging for static files, websocket, health checks, and voice list
    skip = request.url.path.startswith("/static") or request.url.path in ("/ws/logs", "/health", "/stats", "/voices", "/")
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
    text_preview = req.input[:80] + ("..." if len(req.input) > 80 else "")
    _log_json(request_id, "stream_start", text=text_preview, voice=req.voice, speed=req.speed, chars=len(req.input))

    def generate():
        t0 = time.monotonic()
        total_samples = 0
        segment_count = 0
        yield wav_header(SAMPLE_RATE)
        for segment in tts.synthesize_stream(req.input, voice=req.voice, speed=req.speed):
            pcm = audio_to_pcm16(segment)
            total_samples += len(segment)
            segment_count += 1
            seg_dur = len(segment) / SAMPLE_RATE
            _log_json(request_id, "stream_segment", segment=segment_count, segment_duration=f"{seg_dur:.2f}s")
            yield pcm
        elapsed_ms = (time.monotonic() - t0) * 1000
        duration = total_samples / SAMPLE_RATE
        _log_json(request_id, "stream_complete", audio_duration=f"{duration:.2f}s", synth_time=f"{elapsed_ms:.0f}ms", segments=segment_count)
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
    text_preview = req.input[:80] + ("..." if len(req.input) > 80 else "")
    _log_json(request_id, "synth_start", text=text_preview, voice=req.voice, speed=req.speed, chars=len(req.input))

    t0 = time.monotonic()
    audio, sr = tts.synthesize(req.input, voice=req.voice, speed=req.speed)
    elapsed_ms = (time.monotonic() - t0) * 1000

    if len(audio) == 0:
        _log_json(request_id, "synth_empty", error="No audio generated")
        raise HTTPException(status_code=400, detail="No audio generated")

    duration = len(audio) / sr
    _log_json(request_id, "synth_complete", audio_duration=f"{duration:.2f}s", synth_time=f"{elapsed_ms:.0f}ms", size=f"{len(audio)*2//1024}KB")
    global _req_count, _total_audio_sec, _total_synth_ms
    _req_count += 1
    _total_audio_sec += duration
    _total_synth_ms += elapsed_ms

    buf = io.BytesIO()
    import soundfile as sf_write
    sf_write.write(buf, audio, sr, format="WAV", subtype="PCM_16")
    wav_bytes = buf.getvalue()

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


# Mount static files last (so explicit routes take priority)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
