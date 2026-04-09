# Overview

#overview #architecture

A FastAPI server for [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M), an open-weight text-to-speech model with 82 million parameters. The service provides an OpenAI-compatible streaming API, audio caching with content-addressed deduplication, batch processing, and a web-based dashboard.

## Project Purpose and Goals

1. **Serve Kokoro-82M over HTTP** — Load the model once into memory and expose it via a REST API so any application can synthesize speech without managing Python/PyTorch dependencies directly.
2. **OpenAI API compatibility** — The `/v1/audio/speech` endpoint accepts the same request shape as the OpenAI TTS API, making it a drop-in replacement for local inference.
3. **Audio caching** — Identical requests return cached WAV files instantly, eliminating redundant GPU/CPU work and reducing latency to disk-read speed.
4. **Batch processing** — Submit multiple synthesis requests in one call; processing happens asynchronously with per-item status tracking.
5. **Observability** — Structured JSON logging, WebSocket live log streaming, generation history, and system metrics available through the API and web UI.
6. **Self-contained deployment** — A single `docker compose up` brings up the TTS server and MongoDB with persistent volumes.

## Key Features

| Feature | Description |
|---------|-------------|
| Streaming synthesis | WAV audio streamed as segments are generated |
| Full synthesis | Complete WAV with metadata headers (`X-Audio-Duration`, `X-Sample-Rate`, `X-Voice`) |
| Audio cache | SHA-256 content-addressed cache with configurable TTL, size limits, tagging |
| Batch jobs | Async job queue with per-item progress tracking via MongoDB |
| 11 voices | Across 9 languages (American/British English, Japanese, Mandarin, Spanish, French, Hindi, Italian, Portuguese) |
| Web dashboard | Real-time logs, generation history, cache browser, system metrics |
| Shell client | `speak.sh` for command-line TTS with local audio playback |
| Graceful degradation | Server operates without MongoDB (caching and persistence disabled) |

## Technology Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Web framework | FastAPI | Async HTTP + WebSocket server |
| ASGI server | Uvicorn | Production HTTP server |
| TTS model | Kokoro-82M via `kokoro` package | Neural text-to-speech inference |
| ML runtime | PyTorch (CPU) | Model execution |
| Phonemizer | espeak-ng, misaki[ja], misaki[zh] | Text-to-phoneme conversion |
| Database | MongoDB 7 via Motor (async) | Persistence for logs, generations, cache metadata, settings, batch jobs |
| Audio I/O | soundfile, numpy | WAV encoding/decoding |
| Containerization | Docker, Docker Compose | Packaging and orchestration |
| Language | Python 3.12 | Application code |

## Related Pages

- [[Architecture]] — How these components fit together
- [[Setup and Installation]] — Getting started
- [[API — Speech Endpoints]] — Primary synthesis endpoints
