"""Kokoro TTS FastAPI server — keeps the model hot in memory."""

import io
import logging
import struct
import sys
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from kokoro_sdk import SAMPLE_RATE, KokoroTTS

# ---------------------------------------------------------------------------
# Structured JSON logging
# ---------------------------------------------------------------------------
logger = logging.getLogger("kokoro-server")
logger.setLevel(logging.INFO)

handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(logging.Formatter(
    '{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":%(message)s}'
))
logger.addHandler(handler)

# Suppress noisy torch/hf warnings from cluttering logs
logging.getLogger("torch").setLevel(logging.ERROR)
logging.getLogger("huggingface_hub").setLevel(logging.WARNING)

# ---------------------------------------------------------------------------
# App state
# ---------------------------------------------------------------------------
_start_time: float = 0
tts: KokoroTTS | None = None


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


app = FastAPI(title="Kokoro TTS", version="0.1.0", lifespan=lifespan)

# ---------------------------------------------------------------------------
# Request logging middleware
# ---------------------------------------------------------------------------

@app.middleware("http")
async def log_requests(request: Request, call_next):
    request_id = str(uuid.uuid4())[:8]
    request.state.request_id = request_id
    t0 = time.monotonic()
    response = await call_next(request)
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
    # RIFF header with max size placeholder for streaming
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
    logger.info(
        f'{{"request_id":"{request_id}",'
        f'"event":"synthesis_start",'
        f'"text_length":{len(req.input)},'
        f'"voice":"{req.voice}",'
        f'"speed":{req.speed}}}'
    )

    def generate():
        t0 = time.monotonic()
        total_samples = 0
        # WAV header with unknown size (streaming)
        yield wav_header(SAMPLE_RATE)
        for segment in tts.synthesize_stream(req.input, voice=req.voice, speed=req.speed):
            pcm = audio_to_pcm16(segment)
            total_samples += len(segment)
            yield pcm
        elapsed_ms = (time.monotonic() - t0) * 1000
        duration = total_samples / SAMPLE_RATE
        logger.info(
            f'{{"request_id":"{request_id}",'
            f'"event":"synthesis_complete",'
            f'"duration_audio":{duration:.2f},'
            f'"duration_ms":{elapsed_ms:.1f}}}'
        )

    return StreamingResponse(generate(), media_type="audio/wav")


@app.post("/synthesize")
async def synthesize(req: SpeechRequest):
    """Full WAV response with metadata headers."""
    if tts is None:
        raise HTTPException(status_code=503, detail="Model not loaded")

    request_id = str(uuid.uuid4())[:8]
    logger.info(
        f'{{"request_id":"{request_id}",'
        f'"event":"synthesis_start",'
        f'"text_length":{len(req.input)},'
        f'"voice":"{req.voice}",'
        f'"speed":{req.speed}}}'
    )

    t0 = time.monotonic()
    audio, sr = tts.synthesize(req.input, voice=req.voice, speed=req.speed)
    elapsed_ms = (time.monotonic() - t0) * 1000

    if len(audio) == 0:
        raise HTTPException(status_code=400, detail="No audio generated")

    duration = len(audio) / sr
    logger.info(
        f'{{"request_id":"{request_id}",'
        f'"event":"synthesis_complete",'
        f'"duration_audio":{duration:.2f},'
        f'"duration_ms":{elapsed_ms:.1f}}}'
    )

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
