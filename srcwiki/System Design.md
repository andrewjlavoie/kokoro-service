# System Design

#design #architecture

## Design Philosophy

The Kokoro TTS Service is designed around three principles:

1. **Simplicity** — A single Python process serves the API, runs the model, and manages the cache. No message queues, no worker processes, no microservices. The entire application fits in ~20 source files totaling ~1,600 lines.

2. **Optional persistence** — Every MongoDB operation is guarded by a `get_db() is None` check. The server works as a stateless TTS API without any database — you only need MongoDB if you want caching, batch processing, logging, or generation history.

3. **Compatibility** — The `/v1/audio/speech` endpoint mirrors the OpenAI TTS API request format. Any client that speaks to `api.openai.com/v1/audio/speech` can point at this server instead.

## Design Patterns

### Lifespan Context Manager (Startup/Shutdown)
FastAPI's `lifespan` async context manager (`src/app.py:23-42`) handles:
- MongoDB connection initialization and index creation
- Cache settings loading from database
- TTS model loading into memory
- Graceful shutdown (closing DB connection)

This ensures the model is hot before the first request arrives and resources are cleaned up on exit.

### Router-based API Organization
Each API domain has its own `APIRouter`:

| Router | File | Prefix | Responsibility |
|--------|------|--------|----------------|
| `speech.router` | `src/api/speech.py` | (none) | Synthesis endpoints |
| `batch.router` | `src/api/batch.py` | (none) | Batch job endpoints |
| `cache_routes.router` | `src/api/cache.py` | (none) | Cache CRUD endpoints |
| `admin.router` | `src/api/admin.py` | (none) | Monitoring and settings |

Routers are included in `app.py` after middleware registration, with static file mounting last so explicit routes take priority.

### Fire-and-Forget Async Tasks
Database writes (logs, generation records, cache stores) are dispatched via `asyncio.create_task()` and never awaited in the request path. This keeps response latency independent of database performance. Failed writes are silently caught by bare `except Exception: pass` blocks.

```python
# Example from src/api/speech.py
asyncio.create_task(persist_log(request_id, "synth_start", text=req.input, ...))
```

### Singleton Global State
`src/core/state.py` holds module-level global variables:
- `tts: KokoroTTS | None` — the model instance
- `start_time: float` — server start timestamp
- `req_count`, `total_audio_sec`, `total_synth_ms` — request counters

This is safe because Uvicorn runs a single Python process with a single event loop. The `track_request()` function updates counters without locking because Python's GIL ensures atomic integer increments.

### Content-Addressed Cache
See [[Component — Cache Manager]] for full details. The key insight: the cache key is a deterministic SHA-256 hash of `(text, voice, speed, lang_code)`, so:
- Identical requests always hit the same cache entry
- No race conditions on concurrent identical requests (MongoDB's unique index + upsert handles duplicates)
- Cache invalidation is unnecessary — the same input always produces the same output

### Pydantic Request Validation
All API request bodies are validated by Pydantic models (`src/api/models.py`):

```python
class SpeechRequest(BaseModel):
    input: str = Field(..., min_length=1, max_length=10000)
    voice: str = "af_heart"
    speed: float = 1.0
    lang_code: str = "a"
```

Invalid requests are rejected with 422 status before reaching any business logic.

## Module Organization

```
src/
├── app.py              # Application entry point
│                       # - FastAPI app creation and configuration
│                       # - Lifespan (startup/shutdown)
│                       # - Request logging middleware
│                       # - Router mounting and static file serving
│
├── api/                # HTTP interface layer
│   ├── models.py       # Pydantic models: SpeechRequest, BatchRequest, TagRequest
│   ├── speech.py       # POST /v1/audio/speech (streaming), POST /synthesize (full)
│   ├── batch.py        # POST/GET /v1/audio/batch
│   ├── cache.py        # GET/DELETE /cache, POST /cache/{id}/tag
│   └── admin.py        # GET /health, /stats, /voices, /languages, /logs, /generations
│                       #   GET/PUT /settings/cache, /settings/logs
│                       #   WS  /ws/logs
│
├── cache/              # Caching subsystem
│   ├── __init__.py     # Re-exports all manager functions
│   └── manager.py      # Cache logic: lookup, store, TTL, settings, CRUD
│
├── core/               # Shared infrastructure
│   ├── state.py        # Global state: TTS instance, counters, /proc readers
│   ├── logging.py      # Structured JSON logger + WebSocket broadcast handler
│   └── audio.py        # WAV header builder, float32-to-PCM16 conversion
│
├── db/                 # Database layer
│   ├── __init__.py     # Re-exports connection + operations
│   ├── connection.py   # Motor client, collection accessors, index creation
│   └── operations.py   # persist_log(), persist_generation(), serialize_dates()
│
└── tts/                # TTS engine
    ├── __init__.py     # Re-exports KokoroTTS, constants
    ├── constants.py    # SAMPLE_RATE (24000), VOICES dict, LANGUAGE_CODES dict
    └── engine.py       # KokoroTTS class: synthesize(), synthesize_stream(), say()
```

## Interface Definitions

### KokoroTTS (`src/tts/engine.py`)

```python
class KokoroTTS:
    def __init__(self, voice="af_heart", lang_code="a", speed=1.0)
    def ensure_pipeline(self, lang_code: str | None = None) -> None
    def synthesize(self, text, voice=None, speed=None, lang_code=None) -> tuple[np.ndarray, int]
    def synthesize_stream(self, text, voice=None, speed=None, lang_code=None) -> Generator[np.ndarray]
    def say(self, text, voice=None, speed=None, lang_code=None) -> None
    @staticmethod
    def list_voices() -> dict[str, str]
    @staticmethod
    def list_languages() -> dict[str, str]
    @property
    def is_loaded(self) -> bool
```

### Cache Manager (`src/cache/manager.py`)

```python
async def lookup(text, voice, speed, lang_code) -> tuple[dict | None, Path | None]
async def store(text, voice, speed, wav_bytes, duration, sample_rate, lang_code) -> dict | None
async def should_cache(text, wav_bytes=None, duration=None) -> bool
async def list_entries(search, tag, voice, lang_code, sort_by, sort_order, skip, limit) -> tuple[list, int]
async def get_entry(cache_id) -> dict | None
async def update_tags(cache_id, tags=None, label=None) -> dict | None
async def delete_entry(cache_id) -> bool
async def load_settings() -> None
async def save_settings(updates) -> dict
async def get_settings() -> dict
async def enforce_ttl() -> int
def compute_cache_key(text, voice, speed, lang_code) -> str
```

### Database Operations (`src/db/operations.py`)

```python
async def persist_log(request_id, event, **kwargs) -> None
async def persist_generation(request_id, text, voice, speed, ...) -> None
def serialize_dates(doc, fields) -> None
```

## Related Pages

- [[Architecture]] — System-level view
- [[Data Flow]] — How data moves through these modules
- [[Component — TTS Engine]] — TTS engine details
