# Component — Core Services

#component #core

**Location:** `src/core/`
**Files:** `state.py`, `logging.py`, `audio.py`

## Purpose

Shared infrastructure used across the application: global state management, structured logging with WebSocket broadcast, and audio format helpers.

---

## Application State (`state.py`)

Module-level globals that hold the TTS instance and runtime counters:

### Variables

| Variable | Type | Description |
|----------|------|-------------|
| `start_time` | `float` | Server start timestamp (set in lifespan) |
| `tts` | `KokoroTTS \| None` | The loaded TTS model instance |
| `req_count` | `int` | Total synthesis requests served |
| `total_audio_sec` | `float` | Cumulative audio seconds generated |
| `total_synth_ms` | `float` | Cumulative synthesis time (ms) |
| `last_cpu_sample` | `tuple` | Previous CPU measurement for delta calculation |

### `track_request(audio_sec, synth_ms=0.0)`
Increments the request counter and accumulates `audio_sec` and `synth_ms` into the running totals. Called after every successful synthesis (including cache hits, where `synth_ms` is 0).

### System Metrics Readers

These read from `/proc` filesystem (Linux only, designed for Docker containers):

#### `read_proc_meminfo() -> dict`
Reads `/proc/meminfo` for `MemTotal`, `MemAvailable`, `MemFree`. Returns values in bytes (converted from kB).

#### `read_process_mem() -> dict`
Reads `/proc/self/status` for `VmRSS` (resident set), `VmPeak` (peak RSS), `VmSize` (virtual memory). Returns values in bytes.

#### `read_cpu_percent() -> float`
Computes CPU usage percentage since the last sample by reading `/proc/stat`. Uses a delta calculation between the current and previous idle/total jiffies.

> [!NOTE]
> These `/proc` readers return empty dicts or `0.0` on non-Linux systems (e.g., macOS development). The `/stats` endpoint still works — it just reports zeros for system metrics.

---

## Structured Logging (`logging.py`)

### Logger Setup

A Python `logging.Logger` named `"kokoro-server"` with two handlers:

1. **Stdout handler** — Writes structured JSON to stdout:
   ```json
   {"time":"2025-01-01 12:00:00","level":"INFO","logger":"kokoro-server","message":{...}}
   ```

2. **WebSocket handler** — Broadcasts log entries to all connected WebSocket clients (see below).

Noisy loggers are suppressed:
- `torch` → ERROR level
- `huggingface_hub` → WARNING level

### `log_json(request_id, event, **kwargs)`
Convenience function that logs a structured JSON event:

```python
log_json("abc123", "synth_start", text="Hello", voice="af_heart", chars=5)
# Logs: {"request_id":"abc123","event":"synth_start","text":"Hello","voice":"af_heart","chars":5}
```

### WebSocket Log Broadcasting

The `WebSocketLogHandler` class:
1. Intercepts every log record
2. Formats it as a JSON string with `time`, `level`, and `message` fields
3. Sends to all clients in `ws_clients` set via `asyncio.create_task`
4. Automatically removes disconnected clients

The `ws_clients` set is managed by the `/ws/logs` WebSocket endpoint in `src/api/admin.py`.

```
Browser ──WS──► /ws/logs ──► ws_clients set
                              ▲
Logger ──► WebSocketLogHandler ┘ (broadcasts to all)
```

---

## Audio Helpers (`audio.py`)

### `wav_header(sample_rate, num_channels=1, bits_per_sample=16, data_size=0xFFFFFFFF)`
Builds a 44-byte WAV (RIFF) header using `struct.pack`.

- For **streaming**: `data_size=0xFFFFFFFF` (unknown length) — the default
- For **complete files**: pass the actual PCM data size

Header structure (example values assume `sample_rate=24000`, `num_channels=1`, `bits_per_sample=16`):
```
Bytes 0-3:   "RIFF"
Bytes 4-7:   data_size + 36 (or 0xFFFFFFFF for streaming)
Bytes 8-11:  "WAVE"
Bytes 12-15: "fmt "
Bytes 16-19: 16 (fmt chunk size)
Bytes 20-21: 1 (PCM format)
Bytes 22-23: 1 (mono)
Bytes 24-27: 24000 (sample rate)
Bytes 28-31: 48000 (byte rate)
Bytes 32-33: 2 (block align)
Bytes 34-35: 16 (bits per sample)
Bytes 36-39: "data"
Bytes 40-43: data size
```

### `audio_to_pcm16(audio) -> bytes`
Converts a numpy float32 array (range [-1.0, 1.0]) to 16-bit signed PCM bytes:

```python
pcm = (audio * 32767).clip(-32768, 32767).astype(np.int16)
return pcm.tobytes()
```

Used in the streaming endpoint to convert each audio segment before yielding.

## Related Pages

- [[Architecture]] — Where core services fit
- [[Component — API Layer]] — Uses logging and state
- [[API — Admin Endpoints]] — Exposes state via /stats
