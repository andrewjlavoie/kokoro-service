# API — Batch Endpoints

#api #batch

**File:** `src/api/batch.py`

Submit multiple synthesis requests in one call. Processing happens asynchronously with per-item status tracking.

> [!WARNING]
> Batch processing requires MongoDB. Returns 503 if the database is unavailable.

---

## POST `/v1/audio/batch`

**Submit a batch of synthesis requests.**

Returns a `job_id` immediately. Processing happens in the background.

### Request

```bash
curl -X POST http://localhost:8880/v1/audio/batch \
  -H "Content-Type: application/json" \
  -d '{
    "items": [
      {"input": "First sentence", "voice": "af_heart"},
      {"input": "Second sentence", "voice": "am_adam"},
      {"input": "Third in Spanish", "voice": "af_heart", "lang_code": "e"}
    ]
  }'
```

### Request Body

| Field | Type | Required | Constraints | Description |
|-------|------|----------|-------------|-------------|
| `items` | array of SpeechRequest | Yes | 1-100 items | Synthesis requests |

Each item in `items` follows the same schema as [[API — Speech Endpoints]] request body.

### Response

```json
{
    "job_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "status": "pending",
    "total_items": 3
}
```

### Processing

Each item is processed sequentially in a background task:

1. **Cache check** — if cached, mark completed with `cache_hit: true`
2. **Synthesis** — run in a thread via `asyncio.to_thread()` to avoid blocking the event loop
3. **Cache store** — store the result in the audio cache
4. **Status update** — update the item status in MongoDB (`completed` or `failed`)

After all items are processed:
- `status: "completed"` if all items succeeded
- `status: "partial"` if any items failed

---

## GET `/v1/audio/batch/{job_id}`

**Check batch job status and per-item progress.**

### Request

```bash
curl http://localhost:8880/v1/audio/batch/a1b2c3d4-e5f6-7890-abcd-ef1234567890
```

### Response

```json
{
    "job_id": "a1b2c3d4-...",
    "status": "partial",
    "total_items": 3,
    "completed_items": 2,
    "failed_items": 1,
    "created_at": "2025-01-01T00:00:00+00:00",
    "started_at": "2025-01-01T00:00:01+00:00",
    "completed_at": "2025-01-01T00:00:05+00:00",
    "items": [
        {
            "index": 0,
            "text": "First sentence",
            "voice": "af_heart",
            "speed": 1.0,
            "lang_code": "a",
            "status": "completed",
            "cache_id": "507f1f77bcf86cd799439011",
            "audio_duration_sec": 1.23,
            "synth_time_ms": 450.2,
            "cache_hit": false,
            "error": null
        },
        {
            "index": 1,
            "text": "Second sentence",
            "voice": "am_adam",
            "speed": 1.0,
            "lang_code": "a",
            "status": "completed",
            "cache_id": "507f1f77bcf86cd799439012",
            "audio_duration_sec": 1.56,
            "synth_time_ms": 0,
            "cache_hit": true,
            "error": null
        },
        {
            "index": 2,
            "text": "Third in Spanish",
            "voice": "af_heart",
            "speed": 1.0,
            "lang_code": "e",
            "status": "failed",
            "cache_id": null,
            "audio_duration_sec": null,
            "synth_time_ms": null,
            "cache_hit": false,
            "error": "Language 'Spanish' requires additional dependencies"
        }
    ]
}
```

### Error Responses

| Status | Condition |
|--------|-----------|
| 404 | Job ID not found |
| 503 | MongoDB unavailable (`POST`: "MongoDB required for batch processing"; `GET`: "MongoDB unavailable") |

---

## GET `/v1/audio/batch`

**List recent batch jobs.**

### Query Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `skip` | int | `0` | Pagination offset |
| `limit` | int | `20` | Page size |

### Response

```json
{
    "jobs": [
        {
            "job_id": "...",
            "status": "completed",
            "total_items": 3,
            "completed_items": 3,
            "failed_items": 0,
            "created_at": "...",
            "started_at": "...",
            "completed_at": "..."
        }
    ],
    "total": 15
}
```

> [!NOTE]
> The list response excludes the `items` array for brevity. Use `GET /v1/audio/batch/{job_id}` for per-item details.

> [!NOTE]
> If MongoDB is unavailable, the list endpoint returns `{"jobs": [], "total": 0}` instead of raising an error.

---

## Batch Job State Machine

```
pending ──► processing ──► completed
                      └──► partial (some items failed)
```

## Retrieving Batch Audio

Completed batch items include a `cache_id`. Use it to download the audio:

```bash
# Get the cache_id from batch status
CACHE_ID="507f1f77bcf86cd799439011"

# Download the audio file
curl http://localhost:8880/cache/$CACHE_ID --output item_0.wav
```

See [[API — Cache Endpoints]] for cache download details.

## Related Pages

- [[Component — API Layer]] — Router implementation
- [[Data Flow]] — Batch processing flow diagram
- [[API — Cache Endpoints]] — Downloading batch results
