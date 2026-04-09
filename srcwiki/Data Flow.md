# Data Flow

#dataflow #architecture

## Request Lifecycle — Streaming Synthesis (`/v1/audio/speech`)

```
Client POST /v1/audio/speech
  │  {"input": "Hello", "voice": "af_heart", "speed": 1.0, "lang_code": "a"}
  ▼
┌─────────────────────────────────────────┐
│ 1. HTTP Middleware (app.py)             │
│    - Assign middleware request_id       │
│    - Start timer                        │
│    - Attach X-Request-ID to response    │
│    Note: Speech endpoint also generates │
│    its own request_id (UUID[:8]) for    │
│    TTS-specific logging/persistence     │
└─────────────┬───────────────────────────┘
              ▼
┌─────────────────────────────────────────┐
│ 2. Pydantic Validation                  │
│    - Validate input (1-10000 chars)     │
│    - Default voice/speed/lang_code      │
│    - 422 if invalid                     │
└─────────────┬───────────────────────────┘
              ▼
┌─────────────────────────────────────────┐
│ 3. Cache Lookup                         │
│    cache_key = SHA256(text|voice|       │
│                       speed|lang_code)  │
│    Query: db.cache.findOne({cache_key}) │
│    ├── HIT: verify file exists on disk  │
│    │   ├── File exists → return WAV     │
│    │   │   (increment hit_count,        │
│    │   │    update last_accessed_at)     │
│    │   └── File missing → delete stale  │
│    │       entry, continue to synthesis │
│    └── MISS: continue to synthesis      │
└─────────────┬───────────────────────────┘
              ▼
┌─────────────────────────────────────────┐
│ 4. Language Pipeline Check              │
│    ensure_pipeline(lang_code)           │
│    - Load/switch KPipeline if needed    │
│    - 400 if language unsupported        │
└─────────────┬───────────────────────────┘
              ▼
┌─────────────────────────────────────────┐
│ 5. Streaming Synthesis                  │
│    StreamingResponse(generate())        │
│    ┌───────────────────────────┐        │
│    │ yield wav_header(24000)   │ ─────► Client receives header
│    │ for segment in pipeline:  │        │
│    │   pcm = to_pcm16(segment) │        │
│    │   yield pcm               │ ─────► Client receives audio chunks
│    │   collect chunks for cache │        │
│    └───────────────────────────┘        │
└─────────────┬───────────────────────────┘
              ▼
┌─────────────────────────────────────────┐
│ 6. Background Tasks (after response)    │
│    - persist_log("stream_complete")     │
│    - persist_generation(...)            │
│    - audio_cache.store(full_wav)        │
│    - state.track_request(duration, ms)  │
└─────────────────────────────────────────┘
```

## Request Lifecycle — Full Synthesis (`/synthesize`)

```
Client POST /synthesize
  │
  ▼
[Middleware] → [Validation] → [Cache Lookup]
  │                                │
  │  Cache HIT ◄───────────────────┤
  │  (return WAV + metadata headers)│
  │                                │
  │  Cache MISS ───────────────────┘
  ▼
┌─────────────────────────────────────────┐
│ Full Synthesis (blocking)               │
│  audio, sr = tts.synthesize(text, ...)  │
│  - Collects ALL segments internally     │
│  - Concatenates into single np.ndarray  │
│  - Encodes to WAV via soundfile         │
└─────────────┬───────────────────────────┘
              ▼
┌─────────────────────────────────────────┐
│ Response (complete WAV)                 │
│  Headers:                               │
│    X-Request-ID: abc12345               │
│    X-Audio-Duration: 2.34               │
│    X-Sample-Rate: 24000                 │
│    X-Voice: af_heart                    │
│  Body: complete WAV file                │
└─────────────┬───────────────────────────┘
              ▼
[Fire-and-forget: persist_log, persist_generation, cache.store]
```

## Batch Processing Flow

```
Client POST /v1/audio/batch
  │  {"items": [{input, voice, speed, lang_code}, ...]}
  ▼
┌─────────────────────────────────────────┐
│ 1. Create Job Record in MongoDB         │
│    {job_id, status:"pending", items:[]} │
│    Return job_id immediately            │
└─────────────┬───────────────────────────┘
              ▼
┌─────────────────────────────────────────┐
│ 2. Background Task: _process_batch()    │
│    status → "processing"                │
│    For each item:                       │
│      ├── Cache lookup                   │
│      │   └── HIT: mark completed        │
│      └── MISS: synthesize in thread     │
│          ├── OK: store in cache,        │
│          │       mark completed          │
│          └── FAIL: mark failed           │
│    Final status: "completed" | "partial"│
└─────────────────────────────────────────┘
              ▲
              │ (poll)
Client GET /v1/audio/batch/{job_id}
  └── Returns job with per-item status
```

> [!NOTE]
> Batch synthesis runs each item via `asyncio.to_thread(tts.synthesize, ...)` to avoid blocking the event loop. The model itself runs synchronously on CPU.

## Data Transformations

### Text → Audio Pipeline

```
Input text (str, 1-10000 chars)
  │
  ▼
KPipeline (kokoro library)
  │  1. Text normalization
  │  2. Phoneme conversion (espeak-ng for most languages,
  │     misaki[ja] for Japanese, misaki[zh] for Chinese)
  │  3. Neural synthesis (Kokoro-82M model)
  │  4. Audio generation at 24000 Hz sample rate
  ▼
Generator[np.ndarray(float32)]   ← segments as they are produced
  │
  ├── Streaming: audio_to_pcm16() per segment → bytes
  │   └── wav_header() + PCM chunks → StreamingResponse
  │
  └── Full: np.concatenate(segments) → soundfile.write() → WAV bytes
```

### Audio Format Details

| Property | Value |
|----------|-------|
| Format | WAV (RIFF) |
| Encoding | PCM 16-bit signed |
| Sample rate | 24,000 Hz |
| Channels | 1 (mono) |
| Byte rate | 48,000 bytes/sec |
| Block align | 2 bytes |

### Cache Key Computation

```python
canonical = f"{text}|{voice}|{speed:.1f}|{lang_code}"
cache_key = SHA256(canonical.encode()).hexdigest()
# Example: "Hello world|af_heart|1.0|a" → "a1b2c3d4e5..."
```

The speed is formatted to 1 decimal place (`.1f`) so that `1.0` and `1.00` produce the same key.

## Data Storage and Persistence

### MongoDB Collections

| Collection | Purpose | Key Fields | Indexes |
|-----------|---------|------------|---------|
| `cache` | Audio cache metadata | `cache_key`, `text`, `voice`, `speed`, `lang_code`, `file_path`, `file_size_bytes`, `audio_duration_sec`, `tags`, `hit_count` | `cache_key` (unique), `tags`, `text` (text search) |
| `generations` | Synthesis history | `request_id`, `text`, `voice`, `speed`, `audio_duration_sec`, `synth_time_ms`, `endpoint`, `cache_hit` | `request_id` (unique), `created_at` (desc) |
| `logs` | Structured event logs | `request_id`, `event`, `level`, `data` | `created_at` (desc), `request_id` |
| `batch_jobs` | Batch job state | `job_id`, `status`, `items[]`, `completed_items`, `failed_items` | `job_id` (unique), `created_at` (desc) |
| `settings` | Configuration | `_id` ("cache" or "logs"), setting fields | (default `_id` index) |

### Filesystem Cache Structure

```
/app/audio_cache/
├── a1/
│   └── a1b2c3d4e5f6...full_sha256.wav
├── 3f/
│   └── 3f8a9b...wav
└── ...
```

Files are sharded into 256 subdirectories based on the first two hex characters of the SHA-256 hash. This prevents any single directory from growing too large.

## Data Validation and Sanitization

| Layer | Validation |
|-------|-----------|
| Pydantic models | `input`: 1-10,000 characters; `items`: 1-100 batch entries |
| Cache manager | `should_cache()`: text length, audio duration, file size, total cache size, entry count |
| TTS engine | `ensure_pipeline()`: validates language code, raises RuntimeError for unsupported languages |
| Database | MongoDB unique indexes prevent duplicate cache entries and generation records |
| Cache lookup | Verifies file exists on disk; removes stale metadata if file is missing |

## Related Pages

- [[Architecture]] — System-level component diagram
- [[Component — Cache Manager]] — Cache implementation details
- [[Component — Database Layer]] — MongoDB schema and operations
- [[API — Speech Endpoints]] — Endpoint specifications
