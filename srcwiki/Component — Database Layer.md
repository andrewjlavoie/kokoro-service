# Component — Database Layer

#component #database

**Location:** `src/db/`
**Files:** `connection.py`, `operations.py`, `__init__.py`

## Purpose

Manages the MongoDB connection via Motor (async MongoDB driver) and provides collection accessors and persistence operations. The database is entirely optional — the server operates without it, just with reduced functionality.

## Connection Management (`connection.py`)

### `init_db()`
Called during FastAPI lifespan startup:

1. Reads `MONGO_URL` and `MONGO_DB` from environment variables
2. Creates an `AsyncIOMotorClient` with 5-second connection timeout
3. Pings the server to verify connectivity
4. Creates indexes on all collections (see below)

### `close_db()`
Called during shutdown. Closes the Motor client and sets module-level `_client` and `_db` to `None`.

### `get_db()`
Returns the database instance, or `None` if not connected. Every database operation in the application checks this before proceeding.

## Collection Accessors

Simple functions that return `_db["collection_name"]`:

| Function | Collection | Description |
|----------|-----------|-------------|
| `generations()` | `generations` | Synthesis history records |
| `logs()` | `logs` | Structured event logs |
| `cache()` | `cache` | Audio cache metadata |
| `batch_jobs()` | `batch_jobs` | Batch processing jobs |
| `settings()` | `settings` | Application configuration |

## Indexes

Created in `init_db()` at startup:

| Collection | Index | Type | Purpose |
|-----------|-------|------|---------|
| `generations` | `request_id` | Unique | Deduplicate generation records |
| `generations` | `created_at` (desc) | Standard | Recent generations query |
| `logs` | `created_at` (desc) | Standard | Recent logs query |
| `logs` | `request_id` | Standard | Filter logs by request |
| `cache` | `cache_key` | Unique | Content-addressed lookup + dedup |
| `cache` | `tags` | Standard | Filter by tag |
| `cache` | `text` | Text | Full-text search on cached text |
| `batch_jobs` | `job_id` | Unique | Job lookup |
| `batch_jobs` | `created_at` (desc) | Standard | Recent jobs query |

## Persistence Operations (`operations.py`)

### `persist_log(request_id: str | None, event, **kwargs)`
Inserts a log document:

```json
{
    "request_id": "abc12345",
    "event": "synth_start",
    "level": "INFO",
    "data": { /* kwargs */ },
    "created_at": "2025-01-01T00:00:00Z"
}
```

Fire-and-forget: wraps the insert in `try/except Exception: pass`.

### `persist_generation(request_id, text, voice, speed, audio_duration_sec, synth_time_ms, sample_rate, audio_size_bytes, endpoint, cache_hit=False, cache_id=None, lang_code="a")`
Inserts a generation record:

```json
{
    "request_id": "abc12345",
    "text": "Hello world",
    "voice": "af_heart",
    "speed": 1.0,
    "lang_code": "a",
    "char_count": 11,
    "audio_duration_sec": 1.23,
    "synth_time_ms": 450.2,
    "sample_rate": 24000,
    "audio_size_bytes": 59132,
    "endpoint": "/v1/audio/speech",
    "cache_hit": false,
    "cache_id": null,
    "created_at": "2025-01-01T00:00:00Z"
}
```

### `serialize_dates(doc: dict, fields: tuple[str, ...]) -> None`
Converts `datetime` fields in a MongoDB document to ISO 8601 strings for JSON serialization. Called before returning documents to API clients.

## Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `MONGO_URL` | `mongodb://localhost:27017` | MongoDB connection string |
| `MONGO_DB` | `kokoro` | Database name |

## Graceful Degradation

When MongoDB is unavailable:

| Feature | Behavior |
|---------|----------|
| Synthesis (`/v1/audio/speech`, `/synthesize`) | Works normally |
| Audio caching | Disabled (every request is a cache miss) |
| Batch processing | Returns 503 |
| Logs persistence | Silently skipped |
| Generation history | Silently skipped |
| Settings persistence | Returns in-memory defaults |
| `/logs`, `/generations` endpoints | Return empty arrays |

## Related Pages

- [[Architecture]] — How the database fits into the system
- [[Component — Cache Manager]] — Primary cache collection consumer
- [[Data Flow]] — Persistence in the request lifecycle
