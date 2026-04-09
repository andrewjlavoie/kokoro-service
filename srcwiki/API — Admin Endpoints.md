# API — Admin Endpoints

#api #admin #monitoring

**File:** `src/api/admin.py`

Monitoring, health checks, voice/language discovery, settings management, log browsing, and generation history.

---

## GET `/`

**Serves the web dashboard.** Returns `static/index.html` via `FileResponse`. Not included in the OpenAPI schema.

---

## GET `/health`

**Health check endpoint.**

```bash
curl http://localhost:8880/health
```

### Response (200)
```json
{
    "status": "ready",
    "model": "Kokoro-82M",
    "uptime_seconds": 3600.5
}
```

### Error Response (503)
```json
{
    "detail": "Model not loaded"
}
```

---

## GET `/stats`

**System, process, and TTS performance metrics.**

```bash
curl http://localhost:8880/stats
```

### Response

```json
{
    "system": {
        "cpu_count": 8,
        "cpu_percent": 12.5,
        "mem_total": 17179869184,
        "mem_available": 8589934592,
        "mem_used": 8589934592
    },
    "process": {
        "rss": 524288000,
        "peak_rss": 536870912,
        "virtual": 2147483648
    },
    "model": {
        "name": "Kokoro-82M",
        "params": "82M",
        "loaded": true,
        "device": "cpu",
        "torch_version": "2.5.1+cpu"
    },
    "tts": {
        "total_requests": 142,
        "total_audio_seconds": 456.78,
        "total_synth_ms": 23456.7,
        "avg_synth_ms": 165.2,
        "requests_per_minute": 2.37
    },
    "server": {
        "uptime_seconds": 3600.5,
        "python_version": "3.12.8"
    }
}
```

> [!NOTE]
> System metrics (`cpu_percent`, `mem_*`, `rss`, etc.) read from `/proc` and are accurate only on Linux. Returns zeros on macOS/Windows.

---

## GET `/voices`

**List available voices.**

```json
{
    "voices": [
        {"id": "af_heart", "name": "American Female - Heart"},
        {"id": "af_bella", "name": "American Female - Bella"},
        ...
    ]
}
```

---

## GET `/languages`

**List supported languages.**

```json
{
    "languages": [
        {"code": "a", "name": "American English"},
        {"code": "b", "name": "British English"},
        {"code": "j", "name": "Japanese"},
        ...
    ]
}
```

---

## GET `/logs`

**List logs from MongoDB with filtering and pagination.**

### Query Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `skip` | int | `0` | Pagination offset |
| `limit` | int | `50` | Page size |
| `event` | string | `""` | Filter by event type (e.g., `synth_start`, `cache_hit`) |
| `request_id` | string | `""` | Filter by request ID |
| `search` | string | `""` | Search in `data.text`, `data.path`, `data.error`, or `request_id` fields |

### Response

```json
{
    "logs": [
        {
            "request_id": "abc12345",
            "event": "synth_complete",
            "level": "INFO",
            "data": {
                "audio_duration": 1.23,
                "synth_time_ms": 450.2,
                "size_bytes": 59132
            },
            "created_at": "2025-01-01T00:00:00+00:00"
        }
    ],
    "total": 1024
}
```

### Common Event Types

| Event | Description |
|-------|-------------|
| `stream_start` | Streaming synthesis began |
| `stream_segment` | A segment was yielded |
| `stream_complete` | Streaming synthesis finished |
| `synth_start` | Full synthesis began |
| `synth_complete` | Full synthesis finished |
| `synth_empty` | Synthesis produced no audio |
| `cache_hit` | Request served from cache |
| `http_request` | Middleware logged an HTTP request |
| `batch_submitted` | Batch job created |
| `batch_complete` | Batch job finished |

---

## GET `/logs/events`

**List distinct event types in the logs collection.**

```json
{
    "events": ["batch_complete", "batch_submitted", "cache_hit", "http_request", "stream_complete", "stream_segment", "stream_start", "synth_complete", "synth_start"]
}
```

---

## GET `/generations`

**List generation history.**

### Query Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `skip` | int | `0` | Pagination offset |
| `limit` | int | `50` | Page size |

### Response

```json
{
    "generations": [
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
            "created_at": "2025-01-01T00:00:00+00:00"
        }
    ],
    "total": 142
}
```

---

## GET `/settings/cache`

**Get current cache settings.**

See [[Component — Cache Manager]] for the full settings schema.

## PUT `/settings/cache`

**Update cache settings.**

```bash
curl -X PUT http://localhost:8880/settings/cache \
  -H "Content-Type: application/json" \
  -d '{"max_entries": 10000, "ttl_days": 60}'
```

Only known setting keys are accepted; unknown keys are silently ignored.

## POST `/settings/cache/ttl-cleanup`

**Manually trigger TTL cleanup of expired cache entries.**

```json
{
    "removed": 15
}
```

---

## GET `/settings/logs`

**Get log UI settings.**

```json
{
    "refresh_interval_sec": 5
}
```

## PUT `/settings/logs`

**Update log UI settings.** Only accepts known keys; unknown keys are ignored. Returns 503 if MongoDB is unavailable.

Accepted keys:

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `refresh_interval_sec` | int | `5` | Log polling interval for the web UI |

---

## WS `/ws/logs`

**WebSocket endpoint for real-time log streaming.**

Connect and receive JSON log entries as they are generated:

```javascript
const ws = new WebSocket("ws://localhost:8880/ws/logs");
ws.onmessage = (event) => {
    const entry = JSON.parse(event.data);
    console.log(entry.time, entry.level, entry.message);
};
```

Server ignores any messages sent by the client. The connection stays open until the client disconnects.

## Related Pages

- [[Component — Core Services]] — State and logging implementation
- [[Component — Cache Manager]] — Cache settings
- [[Component — Web UI]] — Dashboard that consumes these endpoints
