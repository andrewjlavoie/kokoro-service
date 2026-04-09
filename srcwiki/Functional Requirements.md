# Functional Requirements

#requirements

## FR-1: Text-to-Speech Synthesis

### FR-1.1: Streaming Synthesis
- **Endpoint:** `POST /v1/audio/speech`
- The system SHALL accept text input (1-10,000 characters) and return streaming WAV audio
- Audio SHALL be streamed as PCM 16-bit mono segments at 24,000 Hz
- The first audio segment SHALL be sent before synthesis of the full text completes
- The WAV header SHALL use an unknown-length marker (`0xFFFFFFFF`) for streaming
- **Acceptance:** Client receives valid WAV audio that can be played by standard audio players

### FR-1.2: Full Synthesis
- **Endpoint:** `POST /synthesize`
- The system SHALL accept the same input as FR-1.1 and return a complete WAV file
- Response headers SHALL include `X-Audio-Duration` (seconds), `X-Sample-Rate` (Hz), and `X-Voice` (voice ID)
- The WAV header SHALL contain the correct data size
- **Acceptance:** Response is a valid WAV file; metadata headers match the audio content

### FR-1.3: Voice Selection
- The system SHALL support multiple voice IDs (default: `af_heart`)
- The system SHALL expose the available voice list via `GET /voices`
- **Constraint:** Voice IDs must match those accepted by the upstream Kokoro-82M model

### FR-1.4: Language Support
- The system SHALL support 9 languages via single-letter codes: `a`, `b`, `j`, `z`, `e`, `f`, `h`, `i`, `p`
- Language switching SHALL load the appropriate phonemizer pipeline
- The system SHALL return 400 for unsupported language codes
- **Acceptance:** Each language code produces phonetically correct audio for the target language

### FR-1.5: Speed Control
- The system SHALL accept a `speed` parameter (float, default 1.0)
- Speed SHALL affect playback rate of the generated audio

---

## FR-2: Audio Caching

### FR-2.1: Automatic Caching
- Synthesis results SHALL be cached automatically after generation
- The cache key SHALL be a SHA-256 hash of `(text, voice, speed, lang_code)`
- Identical requests SHALL return cached audio without running the model
- **Acceptance:** Second identical request returns in <50ms with `X-Cache: hit` header

### FR-2.2: Cache Eligibility
- Caching SHALL be skipped for text shorter than `min_text_length` (default 10)
- Caching SHALL be skipped for text longer than `max_text_length` (default 5000)
- Caching SHALL be skipped for audio longer than `max_audio_duration` seconds (default 120)
- Caching SHALL be skipped for files larger than `max_file_size_mb` (default 50)
- Caching SHALL be skipped when total cache entries reach `max_entries` (default 5000)
- Caching SHALL be skipped when total cache size reaches `max_total_size_mb` (default 1024)

### FR-2.3: Cache Settings
- Cache settings SHALL be configurable via `PUT /settings/cache`
- Settings SHALL persist to MongoDB and survive server restarts
- A master `enabled` toggle SHALL disable all caching

### FR-2.4: TTL Expiration
- Entries not accessed within `ttl_days` SHALL be eligible for removal
- TTL cleanup SHALL be triggerable via `POST /settings/cache/ttl-cleanup`
- When `ttl_days` is 0, entries SHALL never expire

### FR-2.5: Cache CRUD
- `GET /cache` SHALL list entries with search, filter (tag, voice, lang_code), and sort
- `GET /cache/{id}` SHALL download the cached WAV file
- `GET /cache/{id}/meta` SHALL return entry metadata
- `POST /cache/{id}/tag` SHALL update tags and/or label
- `DELETE /cache/{id}` SHALL remove the entry and its WAV file
- **Acceptance:** All CRUD operations work correctly; deleted files are removed from disk

### FR-2.6: Stale Entry Cleanup
- If a cache entry's WAV file is missing from disk, the metadata entry SHALL be deleted on next lookup
- **Acceptance:** `lookup()` for an entry with missing file returns (None, None) and removes the stale document

---

## FR-3: Batch Processing

### FR-3.1: Job Submission
- `POST /v1/audio/batch` SHALL accept 1-100 synthesis items
- The endpoint SHALL return a `job_id` immediately without waiting for processing
- **Constraint:** Requires MongoDB (returns 503 without it)

### FR-3.2: Async Processing
- Each item SHALL be processed sequentially in a background task
- Each item SHALL check the cache before synthesizing
- Synthesis SHALL run in a thread (`asyncio.to_thread`) to avoid blocking the event loop
- Results SHALL be stored in the audio cache

### FR-3.3: Status Tracking
- `GET /v1/audio/batch/{job_id}` SHALL return per-item status (`pending`, `completed`, `failed`)
- The response SHALL include `completed_items` and `failed_items` counts
- Final job status SHALL be `completed` (all succeeded) or `partial` (some failed)

### FR-3.4: Job Listing
- `GET /v1/audio/batch` SHALL list recent jobs with pagination
- Job list SHALL exclude per-item details for brevity

---

## FR-4: Observability

### FR-4.1: Health Check
- `GET /health` SHALL return 200 when the model is loaded and ready
- `GET /health` SHALL return 503 when the model is not loaded

### FR-4.2: System Metrics
- `GET /stats` SHALL return CPU, memory, process, model, TTS performance, and server metrics
- TTS metrics SHALL include total requests, total audio seconds, average synthesis time, and requests per minute

### FR-4.3: Structured Logging
- All log entries SHALL be structured JSON with `request_id`, `event`, and contextual data
- Log entries SHALL be persisted to MongoDB (when available)
- `GET /logs` SHALL support filtering by event type, request ID, and text search

### FR-4.4: WebSocket Log Streaming
- `WS /ws/logs` SHALL push log entries to connected clients in real-time
- Disconnected clients SHALL be automatically removed

### FR-4.5: Generation History
- Every synthesis request SHALL be recorded in the `generations` collection
- Records SHALL include text, voice, speed, duration, synthesis time, endpoint, and cache hit status
- `GET /generations` SHALL list records with pagination

### FR-4.6: Request Tracking
- Every HTTP request (except skipped paths) SHALL be assigned a unique `X-Request-ID` header
- Request ID SHALL appear in all related log entries for correlation

---

## FR-5: Web Interface

### FR-5.1: Dashboard
- `GET /` SHALL serve a web UI accessible in any modern browser
- The UI SHALL provide text input, voice selection, language selection, and synthesis controls
- The UI SHALL display system metrics, live logs, generation history, and cache browser

---

## FR-6: Graceful Degradation

### FR-6.1: MongoDB Optional
- The server SHALL start and serve synthesis requests without MongoDB
- When MongoDB is unavailable: caching, batch processing, logging persistence, and generation history SHALL be silently disabled
- **Acceptance:** `docker run` of just the TTS container (no MongoDB) serves synthesis requests

### FR-6.2: Language Dependencies
- If a language's dependencies are not installed (e.g., Japanese without `pyopenjtalk`), the server SHALL return a clear error message rather than crash
- **Acceptance:** Request with unsupported language returns 400 with descriptive error

---

## Constraints and Limitations

| Constraint | Description |
|-----------|-------------|
| Single model | Only Kokoro-82M is supported; no model selection API |
| CPU inference | Default Docker image ships CPU-only PyTorch; GPU works if CUDA-enabled PyTorch is installed |
| Sequential synthesis | One synthesis at a time per pipeline (no model parallelism) |
| Language switching overhead | Changing language replaces the pipeline |
| WAV only | No MP3, OGG, or other audio format support |
| No authentication | No API keys, tokens, or access control |
| No rate limiting | No built-in request throttling |
| Max 10,000 chars | Single request text length limit |
| Max 100 batch items | Batch size limit |

## Related Pages

- [[Overview]] — Project goals
- [[User Flows]] — How requirements manifest as user scenarios
- [[API — Speech Endpoints]] — Endpoint specifications
