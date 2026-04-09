# Setup and Installation

#setup #installation

## Prerequisites

### Docker (Recommended)
- Docker Engine 20+ with Docker Compose V2
- ~2 GB disk for the Docker image (PyTorch, model weights, system dependencies)
- ~512 MB RAM minimum for model inference (1 GB+ recommended)

### Manual Setup
- Python 3.10+ (3.12 recommended)
- MongoDB 7+ (optional — server works without it)
- System packages: `espeak-ng`, `build-essential`, `cmake` (for `pyopenjtalk` compilation)
- An audio player for `speak.sh`: `pw-play` (PipeWire), `aplay` (ALSA), or `ffplay` (FFmpeg)

---

## Quick Start (Docker)

```bash
docker compose up --build
```

This starts:
- **kokoro-tts** on port `8880` — the TTS server
- **mongodb** on port `27017` (internal) — persistence layer

### First Startup

The first startup downloads model weights (~312 MB) from HuggingFace. This is cached in a Docker volume (`hf-cache`), so subsequent starts are fast.

```
kokoro-tts  | {"time":"...","level":"INFO","message":"Loading Kokoro-82M model..."}
kokoro-tts  | {"time":"...","level":"INFO","message":"Model loaded in 8.3s"}
```

### Verify

```bash
curl http://localhost:8880/health
# {"status":"ready","model":"Kokoro-82M","uptime_seconds":12.3}

curl -X POST http://localhost:8880/synthesize \
  -H "Content-Type: application/json" \
  -d '{"input": "Hello world"}' \
  --output test.wav
# test.wav should be a playable audio file
```

---

## Docker Compose Details

```yaml
services:
  kokoro-tts:
    build: .
    ports:
      - "8880:8880"
    volumes:
      - hf-cache:/root/.cache/huggingface    # Model weights (persistent)
      - audio-cache:/app/audio_cache          # Cached audio files
    environment:
      - HF_HUB_DOWNLOAD_TIMEOUT=120
      - MONGO_URL=mongodb://mongodb:27017
      - MONGO_DB=kokoro
    depends_on:
      - mongodb
    restart: unless-stopped

  mongodb:
    image: mongo:7
    volumes:
      - mongo-data:/data/db
    restart: unless-stopped

volumes:
  hf-cache:       # ~312 MB after first model download
  audio-cache:    # Grows based on cache settings (default max 1 GB)
  mongo-data:     # MongoDB data
```

### Docker Volumes

| Volume | Mount Point | Size | Purpose |
|--------|------------|------|---------|
| `hf-cache` | `/root/.cache/huggingface` | ~312 MB | HuggingFace model weights |
| `audio-cache` | `/app/audio_cache` | 0-1 GB | Cached WAV files |
| `mongo-data` | `/data/db` | Variable | MongoDB data |

---

## Manual Setup (Without Docker)

### 1. Install System Dependencies

**Fedora/RHEL:**
```bash
sudo dnf install espeak-ng cmake gcc-c++
```

**Ubuntu/Debian:**
```bash
sudo apt install espeak-ng build-essential cmake
```

**macOS:**
```bash
brew install espeak-ng cmake
```

### 2. Create Virtual Environment

```bash
python3.12 -m venv venv
source venv/bin/activate
```

### 3. Install Python Dependencies

```bash
# PyTorch (CPU)
pip install torch --index-url https://download.pytorch.org/whl/cpu

# Server dependencies
pip install -r requirements.server.txt

# spaCy English model
pip install en_core_web_sm@https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl

# Japanese dictionary (for Japanese language support)
python -m unidic download
```

### 4. Start MongoDB (Optional)

```bash
# Using Docker:
docker run -d --name kokoro-mongo -p 27017:27017 mongo:7

# Or install natively and start the mongod service
```

### 5. Run the Server

```bash
uvicorn src.app:app --host 0.0.0.0 --port 8880 --log-level warning
```

---

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MONGO_URL` | `mongodb://localhost:27017` | MongoDB connection string |
| `MONGO_DB` | `kokoro` | MongoDB database name |
| `AUDIO_CACHE_DIR` | `/app/audio_cache` | Directory for cached WAV files |
| `HF_HUB_DOWNLOAD_TIMEOUT` | `120` | HuggingFace download timeout (seconds) |
| `KOKORO_TTS_URL` | `http://localhost:8880` | Server URL for `speak.sh` |

### Runtime Settings (via API)

Cache settings are configurable at runtime without restart:

```bash
# View current settings
curl http://localhost:8880/settings/cache

# Update settings
curl -X PUT http://localhost:8880/settings/cache \
  -H "Content-Type: application/json" \
  -d '{"max_entries": 10000, "ttl_days": 60, "max_total_size_mb": 2048}'
```

See [[Component — Cache Manager]] for all available settings.

---

## Development Setup

### Install QA Tools

```bash
pip install -r requirements-dev.txt
```

### Available Make Commands

```bash
make help          # Show all commands
make install-dev   # Install QA tools
make format        # Auto-format with ruff
make lint          # Run linting
make type          # Run type checking (pyright)
make security      # Run security scan (bandit)
make test          # Run tests with coverage
make test-quick    # Run tests without coverage
make qa-quick      # Quick checks (format, lint, type, security)
make qa            # Comprehensive QA (all checks + tests)
make complexity    # Code complexity metrics (radon)
make dead-code     # Find unused code (vulture)
make docstrings    # Check docstring coverage (interrogate)
make clean         # Remove QA artifacts
```

See [[QA and Development]] for details.

---

## Dockerfile Breakdown

```dockerfile
FROM python:3.12-slim

# System deps: espeak-ng (phonemizer), build tools (pyopenjtalk compilation)
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends espeak-ng build-essential cmake \
    && rm -rf /var/lib/apt/lists/*

# Python deps (torch installed separately — largest layer, cached)
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
COPY requirements.server.txt .
RUN pip install --no-cache-dir -r requirements.server.txt

# spaCy model and unidic dictionary
RUN pip install en_core_web_sm@https://...
RUN python -m unidic download

COPY src/ ./src/
COPY static/ ./static/

EXPOSE 8880
CMD ["uvicorn", "src.app:app", "--host", "0.0.0.0", "--port", "8880", "--log-level", "warning"]
```

> [!TIP]
> The Dockerfile installs PyTorch as a separate layer before `requirements.server.txt`. This means changing non-torch dependencies doesn't trigger a re-download of the ~800 MB torch package.

## Related Pages

- [[Overview]] — Project summary
- [[Operations Guide]] — Running and maintaining the service
- [[QA and Development]] — Development workflow
