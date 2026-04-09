# Component — API Layer

#component #api

**Location:** `src/api/`
**Files:** `models.py`, `speech.py`, `batch.py`, `cache.py`, `admin.py`

## Purpose

The API layer defines all HTTP and WebSocket endpoints. It handles request validation, delegates to the TTS engine and cache manager, and formats responses. Each file is a FastAPI `APIRouter` that gets mounted in `src/app.py`.

## Request Models (`src/api/models.py`)

All request bodies are validated by Pydantic:

### `SpeechRequest`
```python
class SpeechRequest(BaseModel):
    input: str = Field(..., min_length=1, max_length=10000)  # required
    voice: str = "af_heart"
    speed: float = 1.0
    lang_code: str = "a"
```

### `BatchRequest`
```python
class BatchRequest(BaseModel):
    items: list[SpeechRequest] = Field(..., min_length=1, max_length=100)
```

### `TagRequest`
```python
class TagRequest(BaseModel):
    tags: list[str] = []
    label: str | None = None
```

## Routers Overview

| Router | Endpoints | Description |
|--------|-----------|-------------|
| `speech.router` | `POST /v1/audio/speech`, `POST /synthesize` | Core synthesis |
| `cache_routes.router` | `GET /cache`, `GET /cache/{cache_id}`, `GET /cache/{cache_id}/meta`, `POST /cache/{cache_id}/tag`, `DELETE /cache/{cache_id}` | Cache CRUD |
| `batch.router` | `POST /v1/audio/batch`, `GET /v1/audio/batch/{job_id}`, `GET /v1/audio/batch` | Batch processing |
| `admin.router` | `GET /`, `/health`, `/stats`, `/voices`, `/languages`, `/logs`, `/logs/events`, `/generations`, `GET/PUT /settings/cache`, `GET/PUT /settings/logs`, `POST /settings/cache/ttl-cleanup`, `WS /ws/logs` | Admin/monitoring |

## Middleware (`src/app.py`)

### Request Logging Middleware
Every HTTP request passes through `log_requests()`:

1. Generates a unique `request_id` (first 8 chars of a UUID)
2. Attaches it to `request.state.request_id`
3. Times the request
4. After response, logs method, path, status, and duration as structured JSON
5. Persists the log to MongoDB via `asyncio.create_task`
6. Adds `X-Request-ID` header to response

**Skipped paths** (no logging): `/static/*`, `/settings/*`, `/ws/logs`, `/health`, `/stats`, `/voices`, `/languages`, `/`, `/generations`, `/logs`, `/logs/events`

## Key Implementation Details

### Streaming vs Full Synthesis
The two speech endpoints differ in how they handle the TTS output:

| Aspect | `/v1/audio/speech` (streaming) | `/synthesize` (full) |
|--------|-------------------------------|---------------------|
| Response type | `StreamingResponse` | `Response` |
| Latency | Low — first audio arrives as first segment is ready | Higher — waits for complete synthesis |
| WAV header | Pre-written with unknown data size (`0xFFFFFFFF`) | Correct data size in header |
| Metadata headers | `X-Request-ID` (from middleware); `X-Cache: hit` on cache hits only | `X-Request-ID`, `X-Audio-Duration`, `X-Sample-Rate`, `X-Voice`, `X-Cache: hit` on cache hits |
| Cache storage | Background task after stream completes (reassembles PCM chunks) | Background task with the complete WAV |
| Use case | Real-time playback | File generation, metadata needed |

### Cache Hit Handling
Both speech endpoints share `_handle_cache_hit()` which:
1. Reads the cached WAV file from disk
2. Logs the cache hit
3. Persists a generation record (with `cache_hit=True`, `synth_time_ms=0`)
4. Updates request counters
5. Returns a `Response` with appropriate headers

### Background Task Pattern (Streaming)
The streaming endpoint uses a mutable dict (`_stream_result`) and list (`_pcm_chunks`) to collect data during the sync generator, then processes them in an async `BackgroundTask`:

```python
_stream_result = {}
_pcm_chunks = []

def generate():       # sync generator — runs in threadpool
    # ... yield chunks, populate _stream_result and _pcm_chunks

async def on_stream_complete():  # async — runs after response
    # ... persist logs, store in cache

return StreamingResponse(generate(), background=BackgroundTask(on_stream_complete))
```

## Related Pages

- [[API — Speech Endpoints]] — Detailed endpoint docs
- [[API — Batch Endpoints]] — Batch processing details
- [[API — Cache Endpoints]] — Cache CRUD details
- [[API — Admin Endpoints]] — Monitoring and settings
- [[Component — TTS Engine]] — What the API calls
- [[Component — Cache Manager]] — Cache lookup/store logic
