# Architecture

#architecture

## System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        Docker Compose                           │
│                                                                 │
│  ┌──────────────────────────────────┐   ┌───────────────────┐  │
│  │         kokoro-tts (port 8880)   │   │   mongodb (27017) │  │
│  │                                  │   │                   │  │
│  │  ┌────────────────────────────┐  │   │  ┌─────────────┐  │  │
│  │  │       FastAPI App          │  │   │  │ Collections │  │  │
│  │  │  ┌──────────────────────┐  │  │   │  │             │  │  │
│  │  │  │   HTTP Middleware    │  │──┼───┼──│ logs        │  │  │
│  │  │  │  (request logging)  │  │  │   │  │ generations │  │  │
│  │  │  └──────────────────────┘  │  │   │  │ cache       │  │  │
│  │  │                            │  │   │  │ batch_jobs  │  │  │
│  │  │  ┌──────┐┌─────┐┌────┐┌────┐│  │   │  │ settings    │  │  │
│  │  │  │Speech││Cache││Btch││Admn││  │   │  └─────────────┘  │  │
│  │  │  │Router││Routr││Rtr ││Rtr ││  │   │                   │  │
│  │  │  └──┬───┘└──┬──┘└─┬──┘└─┬──┘│  │   │  mongo-data vol   │  │
│  │  │     │       │     │     │   │  │   └───────────────────┘  │
│  │  │  ┌──┴───────┴─────┴─────┴──┐│  │                          │
│  │  │  │     Cache Manager      ││  │                          │
│  │  │  └───────────┬────────────┘│  │                          │
│  │  │             │             │  │                          │
│  │  │  ┌──────────┴──────────┐  │  │                          │
│  │  │  │    TTS Engine       │  │  │                          │
│  │  │  │  (Kokoro-82M model) │  │  │                          │
│  │  │  └─────────────────────┘  │  │                          │
│  │  └────────────────────────────┘  │                          │
│  │                                  │                          │
│  │  Volumes:                        │                          │
│  │   hf-cache  → /root/.cache/huggingface │                          │
│  │   audio-cache → /app/audio_cache │                          │
│  └──────────────────────────────────┘                          │
└─────────────────────────────────────────────────────────────────┘

External Clients:
  ├── curl / HTTP clients  →  POST /v1/audio/speech, /synthesize
  ├── speak.sh (shell)     →  POST /synthesize
  └── Web browser          →  GET / (dashboard)
```

## Architectural Principles

### 1. Model-hot-in-memory
The TTS model is loaded once during application startup (in the FastAPI `lifespan` handler) and kept resident in memory. All synthesis requests share the same model instance. This avoids the multi-second cold-start penalty of loading a 312MB model per request.

### 2. Graceful degradation
MongoDB is optional. If the database is unreachable at startup, the server logs a warning and continues operating — synthesis works normally, but caching, batch processing, logging persistence, and generation history are disabled. Every database operation checks `get_db() is None` before proceeding.

### 3. Fire-and-forget persistence
Log and generation records are written to MongoDB via `asyncio.create_task()` — the HTTP response is never blocked waiting for a database write. If a write fails, it is silently discarded (see [[Component — Database Layer]]).

### 4. Content-addressed caching
Audio is cached using a SHA-256 hash of `(text, voice, speed, lang_code)`. Identical requests always produce the same cache key, so cache lookups are O(1) via a MongoDB unique index. Files are stored on disk in a sharded directory structure (`{hash[:2]}/{hash}.wav`).

### 5. Streaming-first
The primary endpoint (`/v1/audio/speech`) streams WAV segments as they are generated. The client receives audio before synthesis completes, reducing perceived latency.

## Component Relationships

```
src/
├── app.py              ← FastAPI app, lifespan, middleware, router mounting
├── api/
│   ├── models.py       ← Pydantic request/response models
│   ├── speech.py       ← /v1/audio/speech, /synthesize
│   ├── batch.py        ← /v1/audio/batch
│   ├── cache.py        ← /cache CRUD
│   └── admin.py        ← /health, /stats, /voices, /settings, /logs, /generations
├── cache/
│   └── manager.py      ← Cache logic (lookup, store, TTL, settings)
├── core/
│   ├── state.py        ← Global app state (TTS instance, counters)
│   ├── logging.py      ← Structured JSON logger + WebSocket broadcast
│   └── audio.py        ← WAV header builder, PCM conversion
├── db/
│   ├── connection.py   ← Motor client, collection accessors, indexes
│   └── operations.py   ← persist_log(), persist_generation(), serialize_dates()
└── tts/
    ├── constants.py    ← SAMPLE_RATE, VOICES, LANGUAGE_CODES
    └── engine.py       ← KokoroTTS class wrapping KPipeline
```

### Dependency Graph

```
app.py
 ├── api/speech.py  → cache/manager, core/state, core/audio, core/logging, db, tts/constants
 ├── api/batch.py   → cache/manager, core/state, core/logging, db
 ├── api/admin.py   → cache/manager, core/state, core/logging, db, tts
 ├── api/cache.py   → cache/manager, api/models
 ├── cache/manager  → db
 ├── core/state     → tts/engine
 ├── db/connection  → motor (MongoDB)
 └── tts/engine     → kokoro (KPipeline), tts/constants
```

> [!TIP]
> No circular dependencies exist. The dependency graph flows strictly downward: API → Cache/Core → DB/TTS. The `tts` and `db` packages have no cross-dependencies.

## Scalability Considerations

| Concern | Current Design | Scaling Path |
|---------|---------------|-------------|
| Model concurrency | Single KPipeline instance, no locking | The model runs on CPU; synthesis is sequential per request. For higher throughput, run multiple container replicas behind a load balancer. |
| Cache storage | Filesystem + MongoDB metadata | The `max_total_size_mb` and `max_entries` settings cap growth. TTL cleanup removes stale entries. For larger deployments, use object storage (S3) with a cache proxy. |
| Batch processing | In-process `asyncio.create_task` | Batch jobs run in the same process. For heavy batch loads, extract to a dedicated worker with a proper task queue (Celery, Redis). |
| Database | Single MongoDB instance | MongoDB replica sets for HA. The schema is simple (no joins, no transactions) so sharding is straightforward. |
| Logging | Fire-and-forget inserts | Acceptable for moderate load. At high volume, buffer writes or use a log aggregator (Loki, Elasticsearch). |

## Related Pages

- [[Overview]] — Project purpose and technology stack
- [[System Design]] — Design patterns and module organization
- [[Data Flow]] — Request lifecycle details
