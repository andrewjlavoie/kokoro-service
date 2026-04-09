# Kokoro TTS Service — Documentation Wiki

> [!NOTE]
> This wiki provides comprehensive technical documentation for the Kokoro TTS Service. It is designed so that someone could build and operate the application from scratch using only this reference.

## Table of Contents

### Foundation
- [[Overview]] — Project purpose, goals, features, and technology stack
- [[Architecture]] — System architecture, component relationships, and design decisions
- [[System Design]] — Design philosophy, patterns, and module organization
- [[Data Flow]] — Request lifecycle, data transformations, and persistence

### Component Reference
- [[Component — TTS Engine]] — Kokoro-82M model wrapper (`src/tts/`)
- [[Component — API Layer]] — FastAPI routers and endpoint definitions (`src/api/`)
- [[Component — Cache Manager]] — Audio cache with SHA-256 deduplication (`src/cache/`)
- [[Component — Database Layer]] — MongoDB connection, collections, and operations (`src/db/`)
- [[Component — Core Services]] — Application state, logging, and audio helpers (`src/core/`)
- [[Component — Web UI]] — Browser-based dashboard (`static/index.html`)
- [[Component — Shell Client]] — `speak.sh` CLI for local playback

### API Reference
- [[API — Speech Endpoints]] — `/v1/audio/speech` and `/synthesize`
- [[API — Batch Endpoints]] — `/v1/audio/batch` submit, poll, and list
- [[API — Cache Endpoints]] — Browse, download, tag, and delete cached audio
- [[API — Admin Endpoints]] — Health, stats, voices, languages, settings, logs, generations

### Guides
- [[User Flows]] — End-to-end scenarios with expected inputs and outputs
- [[Functional Requirements]] — Feature specifications and acceptance criteria
- [[Setup and Installation]] — Prerequisites, Docker, and manual setup
- [[Operations Guide]] — Running, monitoring, troubleshooting, and maintenance
- [[QA and Development]] — Linting, testing, security scanning, and code quality

---

**Project:** kokoro-tts-service v0.2.0
**Model:** [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) (82M parameters, Apache 2.0)
**Runtime:** Python 3.12, FastAPI, PyTorch (CPU), MongoDB 7

#kokoro #tts #documentation
