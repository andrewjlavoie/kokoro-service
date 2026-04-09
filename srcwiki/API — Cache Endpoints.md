# API — Cache Endpoints

#api #cache

**File:** `src/api/cache.py`

CRUD endpoints for browsing, downloading, tagging, and deleting cached audio entries.

---

## GET `/cache`

**List cached audio entries with search, filtering, and sorting.**

### Query Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `search` | string | `""` | Full-text search on cached text content |
| `tag` | string | `""` | Filter by tag (exact match) |
| `voice` | string | `""` | Filter by voice ID |
| `lang_code` | string | `""` | Filter by language code |
| `sort_by` | string | `"created_at"` | Sort field (see below) |
| `sort_order` | int | `-1` | `-1` descending, `1` ascending |
| `skip` | int | `0` | Pagination offset |
| `limit` | int | `50` | Page size |

**Valid sort fields:** `created_at`, `hit_count`, `file_size_bytes`, `audio_duration_sec`, `voice`, `last_accessed_at`

### Response

```json
{
    "entries": [
        {
            "_id": "507f1f77bcf86cd799439011",
            "cache_key": "a1b2c3...",
            "text": "Hello world",
            "voice": "af_heart",
            "speed": 1.0,
            "lang_code": "a",
            "audio_duration_sec": 1.23,
            "sample_rate": 24000,
            "file_path": "a1/a1b2c3...wav",
            "file_size_bytes": 59132,
            "tags": ["greeting", "demo"],
            "label": "Hello World Demo",
            "hit_count": 42,
            "created_at": "2025-01-01T00:00:00+00:00",
            "last_accessed_at": "2025-01-15T12:00:00+00:00"
        }
    ],
    "total": 156
}
```

---

## GET `/cache/{cache_id}/meta`

**Get metadata for a single cache entry.**

### Response

Same schema as a single entry in the list response above.

### Error Responses

| Status | Condition |
|--------|-----------|
| 404 | Cache entry not found |

---

## GET `/cache/{cache_id}`

**Download a cached audio file.**

### Response

| Header | Value |
|--------|-------|
| `Content-Type` | `audio/wav` |
| `Content-Disposition` | `attachment; filename="{voice}_{id[:8]}.wav"` |

**Body:** WAV file bytes

### Error Responses

| Status | Condition |
|--------|-----------|
| 404 | Cache entry not found, or audio file missing from disk |

---

## POST `/cache/{cache_id}/tag`

**Update tags and/or label on a cache entry.**

### Request Body

```json
{
    "tags": ["greeting", "demo"],
    "label": "Hello World Demo"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `tags` | array of string | No | Replace the tags list |
| `label` | string or null | No | Replace the label |

### Response

Returns the updated cache entry (same schema as `/cache/{id}/meta`).

### Error Responses

| Status | Condition |
|--------|-----------|
| 404 | Cache entry not found |

---

## DELETE `/cache/{cache_id}`

**Remove a cached audio entry and its WAV file from disk.**

### Response

```json
{
    "deleted": true
}
```

### Error Responses

| Status | Condition |
|--------|-----------|
| 404 | Cache entry not found |

---

## Cache as Snippet Library

The tagging feature enables using the cache as an audio snippet library:

1. **Generate** audio via the speech endpoints
2. **Browse** cached entries at `GET /cache`
3. **Tag** useful entries with meaningful labels: `POST /cache/{id}/tag`
4. **Search** by tag: `GET /cache?tag=greetings`
5. **Download** audio files: `GET /cache/{id}`
6. **Clean up** unwanted entries: `DELETE /cache/{id}`

## Related Pages

- [[Component — Cache Manager]] — Implementation details
- [[API — Batch Endpoints]] — Downloading batch results via cache IDs
- [[User Flows]] — Cache management scenarios
