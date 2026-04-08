"""Kokoro TTS FastAPI server — keeps the model hot in memory."""

import asyncio
import json
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from src.cache import manager as audio_cache
from src.core import state
from src.core.logging import logger
from src.db import close_db, init_db, persist_log
from src.tts.engine import KokoroTTS

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    state.start_time = time.time()
    # Initialize MongoDB (graceful — server works without it)
    try:
        await init_db()
        logger.info('"MongoDB connected"')
        # Load cache settings from MongoDB
        await audio_cache.load_settings()
    except Exception as e:
        logger.warning(f'"MongoDB unavailable: {e} — running without persistence"')
    # Load TTS model
    logger.info('"Loading Kokoro-82M model..."')
    t0 = time.monotonic()
    state.tts = KokoroTTS()
    state.tts.ensure_pipeline()  # force model load at startup
    elapsed = time.monotonic() - t0
    logger.info(f'"Model loaded in {elapsed:.1f}s"')
    yield
    await close_db()
    logger.info('"Server shutting down"')


app = FastAPI(title="Kokoro TTS", version="0.2.0", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Request logging middleware
# ---------------------------------------------------------------------------


@app.middleware("http")
async def log_requests(request: Request, call_next):
    # Skip logging for static files, websocket, health checks, and voice list
    skip = (
        request.url.path.startswith("/static")
        or request.url.path.startswith("/settings")
        or request.url.path
        in ("/ws/logs", "/health", "/stats", "/voices", "/languages", "/", "/generations", "/logs", "/logs/events")
    )
    request_id = str(uuid.uuid4())[:8]
    request.state.request_id = request_id
    t0 = time.monotonic()
    response = await call_next(request)
    if not skip:
        elapsed_ms = (time.monotonic() - t0) * 1000
        logger.info(
            json.dumps(
                {
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "duration_ms": round(elapsed_ms, 1),
                }
            )
        )
        asyncio.create_task(
            persist_log(
                request_id,
                "http_request",
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                duration_ms=round(elapsed_ms, 1),
            )
        )
    response.headers["X-Request-ID"] = request_id
    return response


# ---------------------------------------------------------------------------
# Include routers
# ---------------------------------------------------------------------------

from src.api import admin, batch, speech  # noqa: E402
from src.api import cache as cache_routes  # noqa: E402

app.include_router(speech.router)
app.include_router(cache_routes.router)
app.include_router(batch.router)
app.include_router(admin.router)

# Mount static files last (so explicit routes take priority)
app.mount("/static", StaticFiles(directory=_PROJECT_ROOT / "static"), name="static")
