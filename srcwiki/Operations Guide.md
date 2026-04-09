# Operations Guide

#operations #monitoring

## Running the Application

### Docker (Production)

```bash
# Start
docker compose up -d

# View logs
docker compose logs -f kokoro-tts

# Stop
docker compose down

# Rebuild after code changes
docker compose up --build -d
```

### Manual (Development)

```bash
source venv/bin/activate
uvicorn src.app:app --host 0.0.0.0 --port 8880 --log-level warning
```

For development with auto-reload:
```bash
uvicorn src.app:app --host 0.0.0.0 --port 8880 --reload
```

---

## Monitoring

### Health Check

```bash
curl http://localhost:8880/health
```

| Response | Meaning |
|----------|---------|
| `200 {"status": "ready"}` | Model loaded, accepting requests |
| `503 {"detail": "Model not loaded"}` | Still loading or failed to load |

### System Metrics

```bash
curl http://localhost:8880/stats | jq .
```

Key metrics to watch:

| Metric | Location | Concern Threshold |
|--------|----------|-------------------|
| `system.mem_available` | `/stats` | < 500 MB (model needs ~400 MB RSS) |
| `system.cpu_percent` | `/stats` | Sustained > 90% (CPU-bound synthesis) |
| `process.rss` | `/stats` | > 2 GB (possible memory leak) |
| `tts.avg_synth_ms` | `/stats` | > 5000ms (performance degradation) |
| `tts.total_requests` | `/stats` | Monitor for traffic patterns |

### Real-Time Logs

**WebSocket (browser/tool):**
```javascript
const ws = new WebSocket("ws://localhost:8880/ws/logs");
ws.onmessage = (e) => console.log(JSON.parse(e.data));
```

**Web UI:** Navigate to `http://localhost:8880/` and watch the live log panel.

**Container logs:**
```bash
docker compose logs -f kokoro-tts --tail 100
```

### Log Query API

```bash
# Recent logs
curl "http://localhost:8880/logs?limit=20"

# Filter by event type
curl "http://localhost:8880/logs?event=synth_complete"

# Search by text content
curl "http://localhost:8880/logs?search=error"

# Trace a specific request
curl "http://localhost:8880/logs?request_id=abc12345"
```

---

## Log Format

All logs are structured JSON written to stdout:

```json
{"time":"2025-01-01 12:00:00","level":"INFO","logger":"kokoro-server","message":{"request_id":"abc12345","event":"synth_complete","audio_duration":"1.87s","synth_time":"432ms"}}
```

### Key Event Types

| Event | When | Important Fields |
|-------|------|-----------------|
| `stream_start` | Streaming synthesis begins | `text`, `voice`, `chars` |
| `stream_complete` | Streaming synthesis ends | `audio_duration`, `synth_time`, `segments` |
| `synth_start` | Full synthesis begins | `text`, `voice`, `chars` |
| `synth_complete` | Full synthesis ends | `audio_duration`, `synth_time`, `size` |
| `cache_hit` | Request served from cache | `text`, `voice`, `cache_key` |
| `synth_empty` | No audio produced | `error` |
| `http_request` | HTTP request completed | `method`, `path`, `status`, `duration_ms` |
| `batch_submitted` | Batch job created | `job_id`, `total_items` |
| `batch_complete` | Batch job finished | `job_id`, `status`, `completed`, `failed` |

---

## Troubleshooting

### Model fails to load

**Symptom:** Server returns 503 on all synthesis endpoints.

**Cause:** Model weights failed to download or espeak-ng is missing.

**Fix:**
```bash
# Check logs for error
docker compose logs kokoro-tts | grep -i error

# Verify HuggingFace is reachable
docker compose exec kokoro-tts python -c "from huggingface_hub import hf_hub_download; print('OK')"

# Check espeak-ng
docker compose exec kokoro-tts espeak-ng --version
```

### MongoDB connection failures

**Symptom:** Logs show "MongoDB unavailable" at startup. Caching and batch processing don't work.

**Fix:**
```bash
# Check MongoDB container
docker compose ps mongodb

# Verify connectivity from TTS container
docker compose exec kokoro-tts python -c "
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
async def check():
    c = AsyncIOMotorClient('mongodb://mongodb:27017', serverSelectionTimeoutMS=5000)
    await c.admin.command('ping')
    print('MongoDB OK')
asyncio.run(check())
"
```

> [!NOTE]
> The server works without MongoDB — synthesis endpoints function normally, but caching, batch processing, logging, and generation history are disabled.

### Out of memory

**Symptom:** Container killed (OOMKilled) or `process.rss` in `/stats` grows unbounded.

**Fix:**
- Ensure at least 1 GB RAM is available for the container
- Set memory limits in Docker Compose:
  ```yaml
  kokoro-tts:
    deploy:
      resources:
        limits:
          memory: 2G
  ```

### Slow synthesis

**Symptom:** `tts.avg_synth_ms` in `/stats` is higher than expected.

**Causes:**
- Long input text (synthesis time scales with text length)
- CPU contention from other processes
- Language pipeline switching overhead

**Mitigations:**
- Split long text into smaller chunks
- Ensure the container has dedicated CPU cores
- Use batch processing for large workloads

### Cache not working

**Symptom:** `X-Cache: hit` header never appears; every request synthesizes from scratch.

**Check:**
```bash
# Verify cache settings
curl http://localhost:8880/settings/cache
# Check that "enabled" is true

# Check cache entries
curl http://localhost:8880/cache
# Should show entries after the first synthesis

# Check if text is too short (default min: 10 chars)
curl http://localhost:8880/settings/cache | jq .min_text_length
```

### Audio playback issues with speak.sh

**Symptom:** `speak.sh` synthesizes but no audio plays.

**Fix:**
```bash
# Check available audio players
which pw-play aplay ffplay

# Install one if missing (Fedora)
sudo dnf install pipewire-utils
# or
sudo dnf install alsa-utils

# Test playback directly
curl -X POST http://localhost:8880/synthesize \
  -H "Content-Type: application/json" \
  -d '{"input": "test"}' -o /tmp/test.wav
pw-play /tmp/test.wav
```

---

## Maintenance

### Cache Cleanup

```bash
# Check cache size
curl http://localhost:8880/cache | jq .total

# Run TTL cleanup (removes entries older than ttl_days)
curl -X POST http://localhost:8880/settings/cache/ttl-cleanup
# {"removed": 15}

# Delete specific entry
curl -X DELETE http://localhost:8880/cache/{cache_id}
```

### Database Maintenance

```bash
# Connect to MongoDB
docker compose exec mongodb mongosh kokoro

# Check collection sizes
db.stats()

# Check index sizes
db.cache.stats().indexSizes
db.logs.stats().indexSizes

# Compact collections (if needed)
db.runCommand({compact: "logs"})
```

### Volume Management

```bash
# List volumes
docker volume ls | grep kokoro

# Check volume sizes
docker system df -v | grep kokoro

# Remove all data (destructive!)
docker compose down -v
```

### Updating

```bash
# Pull latest code
git pull

# Rebuild and restart
docker compose up --build -d

# Verify
curl http://localhost:8880/health
```

## Related Pages

- [[Setup and Installation]] — Initial setup
- [[Architecture]] — System overview
- [[Component — Cache Manager]] — Cache settings and behavior
- [[API — Admin Endpoints]] — Monitoring endpoints
