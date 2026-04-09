# Component — Web UI

#component #webui

**Location:** `static/index.html`
**Served at:** `GET /` (via `FileResponse`) and `/static/` (via `StaticFiles`)

## Purpose

A single-page browser dashboard for interacting with the TTS service. Provides a synthesis interface, real-time log viewer, generation history, cache browser, and system metrics.

## Access

Navigate to `http://localhost:8880/` in a web browser. The UI is a self-contained HTML file with inline CSS and JavaScript — no build step or external dependencies.

## Features

The web UI consumes the following API endpoints:

| UI Section | Endpoints Used |
|-----------|---------------|
| Synthesis | `POST /synthesize` |
| Voice selector | `GET /voices` |
| Language selector | `GET /languages` |
| Live logs | `WS /ws/logs` |
| Log history | `GET /logs`, `GET /logs/events` |
| Generation history | `GET /generations` |
| Cache browser | `GET /cache`, `GET /cache/{id}`, `DELETE /cache/{id}`, `POST /cache/{id}/tag` |
| System metrics | `GET /stats` |
| Health indicator | `GET /stats` (derived from `model.loaded`) |
| Cache settings | `GET /settings/cache`, `PUT /settings/cache`, `POST /settings/cache/ttl-cleanup` |
| Log settings | `GET /settings/logs`, `PUT /settings/logs` |
| Batch queue | `POST /v1/audio/batch`, `GET /v1/audio/batch/{id}`, `GET /v1/audio/batch` |

## WebSocket Log Streaming

The UI connects to `ws://localhost:8880/ws/logs` on page load. The WebSocket is used for new-log notification badges (incrementing the unread count). The log feed itself is populated via HTTP polling of `GET /logs`.

Log entries arrive as JSON:

```json
{
    "time": "2025-01-15 12:34:56",
    "level": "INFO",
    "message": {"request_id": "abc123", "event": "synth_start", ...}
}
```

The connection is kept alive via periodic `receive_text()` on the server side. If the WebSocket disconnects, the client in `ws_clients` is automatically cleaned up.

## Static File Serving

Static files are mounted last in `src/app.py`:

```python
app.mount("/static", StaticFiles(directory=_PROJECT_ROOT / "static"), name="static")
```

This ensures explicit API routes take priority over the static file handler. The root `/` endpoint is an explicit route that serves `static/index.html` via `FileResponse`.

## Related Pages

- [[API — Admin Endpoints]] — Backend endpoints the UI consumes
- [[Component — Core Services]] — WebSocket log broadcasting
- [[User Flows]] — How users interact through the UI
