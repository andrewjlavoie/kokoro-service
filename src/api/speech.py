"""TTS synthesis endpoints — OpenAI-compatible streaming and full WAV."""

import asyncio
import io
import time
import uuid

import soundfile as sf
from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from src.api.models import SpeechRequest
from src.cache import manager as audio_cache
from src.core import state
from src.core.audio import audio_to_pcm16, wav_header
from src.core.logging import log_json
from src.db import persist_generation, persist_log
from src.tts.constants import SAMPLE_RATE

router = APIRouter()


async def _handle_cache_hit(
    request_id: str, req: SpeechRequest, cache_doc, cache_path, endpoint: str
) -> Response | None:
    """Return a Response for a cache hit, or None if no hit."""
    if not (cache_doc and cache_path):
        return None
    log_json(request_id, "cache_hit", text=req.input, voice=req.voice, cache_key=cache_doc["cache_key"][:12])
    asyncio.create_task(
        persist_log(request_id, "cache_hit", text=req.input, voice=req.voice, speed=req.speed, lang_code=req.lang_code)
    )
    asyncio.create_task(
        persist_generation(
            request_id=request_id,
            text=req.input,
            voice=req.voice,
            speed=req.speed,
            lang_code=req.lang_code,
            audio_duration_sec=cache_doc["audio_duration_sec"],
            synth_time_ms=0,
            sample_rate=cache_doc["sample_rate"],
            audio_size_bytes=cache_doc["file_size_bytes"],
            endpoint=endpoint,
            cache_hit=True,
            cache_id=str(cache_doc["_id"]),
        )
    )
    state.track_request(cache_doc["audio_duration_sec"])
    wav_bytes = cache_path.read_bytes()
    headers = {"X-Request-ID": request_id, "X-Cache": "hit"}
    if endpoint == "/synthesize":
        headers["X-Audio-Duration"] = f"{cache_doc['audio_duration_sec']:.2f}"
        headers["X-Sample-Rate"] = str(cache_doc["sample_rate"])
        headers["X-Voice"] = req.voice
    return Response(content=wav_bytes, media_type="audio/wav", headers=headers)


@router.post("/v1/audio/speech")
async def speech_stream(req: SpeechRequest):
    """OpenAI-compatible TTS endpoint with streaming audio."""
    if state.tts is None:
        raise HTTPException(status_code=503, detail="Model not loaded")

    request_id = str(uuid.uuid4())[:8]

    # Check cache — return full WAV immediately on hit
    cache_doc, cache_path = await audio_cache.lookup(req.input, req.voice, req.speed, req.lang_code)
    hit = await _handle_cache_hit(request_id, req, cache_doc, cache_path, "/v1/audio/speech")
    if hit:
        return hit

    # Validate language pipeline before streaming
    try:
        state.tts.ensure_pipeline(req.lang_code)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None

    log_json(
        request_id,
        "stream_start",
        text=req.input,
        voice=req.voice,
        speed=req.speed,
        lang_code=req.lang_code,
        chars=len(req.input),
    )
    asyncio.create_task(
        persist_log(
            request_id,
            "stream_start",
            text=req.input,
            voice=req.voice,
            speed=req.speed,
            lang_code=req.lang_code,
            chars=len(req.input),
        )
    )

    # Mutable container for data collected during streaming
    _stream_result = {}
    _pcm_chunks = []

    def generate():
        t0 = time.monotonic()
        total_samples = 0
        segment_count = 0
        yield wav_header(SAMPLE_RATE)
        for segment in state.tts.synthesize_stream(
            req.input, voice=req.voice, speed=req.speed, lang_code=req.lang_code
        ):
            pcm = audio_to_pcm16(segment)
            _pcm_chunks.append(pcm)
            total_samples += len(segment)
            segment_count += 1
            seg_dur = len(segment) / SAMPLE_RATE
            log_json(request_id, "stream_segment", segment=segment_count, segment_duration=f"{seg_dur:.2f}s")
            yield pcm
        elapsed_ms = (time.monotonic() - t0) * 1000
        duration = total_samples / SAMPLE_RATE
        log_json(
            request_id,
            "stream_complete",
            audio_duration=f"{duration:.2f}s",
            synth_time=f"{elapsed_ms:.0f}ms",
            segments=segment_count,
        )
        _stream_result["elapsed_ms"] = elapsed_ms
        _stream_result["duration"] = duration
        _stream_result["total_samples"] = total_samples
        _stream_result["segment_count"] = segment_count

    async def on_stream_complete():
        """Persist logs, generation record, and cache after streaming finishes."""
        elapsed_ms = _stream_result.get("elapsed_ms", 0)
        duration = _stream_result.get("duration", 0)
        total_samples = _stream_result.get("total_samples", 0)
        await persist_log(
            request_id,
            "stream_complete",
            audio_duration=duration,
            synth_time_ms=elapsed_ms,
            segments=_stream_result.get("segment_count", 0),
        )
        await persist_generation(
            request_id=request_id,
            text=req.input,
            voice=req.voice,
            speed=req.speed,
            lang_code=req.lang_code,
            audio_duration_sec=duration,
            synth_time_ms=elapsed_ms,
            sample_rate=SAMPLE_RATE,
            audio_size_bytes=total_samples * 2,
            endpoint="/v1/audio/speech",
        )
        all_pcm = b"".join(_pcm_chunks)
        pcm_size = len(all_pcm)
        full_wav = wav_header(SAMPLE_RATE, data_size=pcm_size) + all_pcm
        await audio_cache.store(req.input, req.voice, req.speed, full_wav, duration, SAMPLE_RATE, req.lang_code)
        state.track_request(duration, elapsed_ms)

    return StreamingResponse(
        generate(),
        media_type="audio/wav",
        background=BackgroundTask(on_stream_complete),
    )


@router.post("/synthesize")
async def synthesize(req: SpeechRequest):
    """Full WAV response with metadata headers."""
    if state.tts is None:
        raise HTTPException(status_code=503, detail="Model not loaded")

    request_id = str(uuid.uuid4())[:8]

    # Check cache first
    cache_doc, cache_path = await audio_cache.lookup(req.input, req.voice, req.speed, req.lang_code)
    hit = await _handle_cache_hit(request_id, req, cache_doc, cache_path, "/synthesize")
    if hit:
        return hit

    # Validate language pipeline
    try:
        state.tts.ensure_pipeline(req.lang_code)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None

    log_json(
        request_id,
        "synth_start",
        text=req.input,
        voice=req.voice,
        speed=req.speed,
        lang_code=req.lang_code,
        chars=len(req.input),
    )
    asyncio.create_task(
        persist_log(
            request_id,
            "synth_start",
            text=req.input,
            voice=req.voice,
            speed=req.speed,
            lang_code=req.lang_code,
            chars=len(req.input),
        )
    )

    t0 = time.monotonic()
    audio, sr = state.tts.synthesize(req.input, voice=req.voice, speed=req.speed, lang_code=req.lang_code)
    elapsed_ms = (time.monotonic() - t0) * 1000

    if len(audio) == 0:
        log_json(request_id, "synth_empty", error="No audio generated")
        asyncio.create_task(
            persist_log(request_id, "synth_empty", text=req.input, voice=req.voice, error="No audio generated")
        )
        raise HTTPException(status_code=400, detail="No audio generated")

    duration = len(audio) / sr
    log_json(
        request_id,
        "synth_complete",
        audio_duration=f"{duration:.2f}s",
        synth_time=f"{elapsed_ms:.0f}ms",
        size=f"{len(audio) * 2 // 1024}KB",
    )
    asyncio.create_task(
        persist_log(
            request_id, "synth_complete", audio_duration=duration, synth_time_ms=elapsed_ms, size_bytes=len(audio) * 2
        )
    )
    state.track_request(duration, elapsed_ms)

    buf = io.BytesIO()
    sf.write(buf, audio, sr, format="WAV", subtype="PCM_16")
    wav_bytes = buf.getvalue()

    asyncio.create_task(
        persist_generation(
            request_id=request_id,
            text=req.input,
            voice=req.voice,
            speed=req.speed,
            lang_code=req.lang_code,
            audio_duration_sec=duration,
            synth_time_ms=elapsed_ms,
            sample_rate=sr,
            audio_size_bytes=len(wav_bytes),
            endpoint="/synthesize",
        )
    )
    # Store in cache
    asyncio.create_task(audio_cache.store(req.input, req.voice, req.speed, wav_bytes, duration, sr, req.lang_code))

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
