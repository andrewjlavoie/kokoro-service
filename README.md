# Kokoro TTS Service

A FastAPI server for [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M), an open-weight text-to-speech model with 82 million parameters. Provides OpenAI-compatible streaming, audio caching, batch processing, and a web UI.

## Quick Start (Docker)

```bash
docker compose up --build
```

This starts the TTS server on **port 8880** with a MongoDB instance for persistence.

The first startup downloads model weights (~312MB) from HuggingFace, which may take a few minutes.

## API Endpoints

### Streaming (OpenAI-compatible)

```bash
curl -X POST http://localhost:8880/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"input": "Hello world", "voice": "af_heart"}' \
  --output speech.wav
```

### Full synthesis with metadata

```bash
curl -X POST http://localhost:8880/synthesize \
  -H "Content-Type: application/json" \
  -d '{"input": "Hello world", "voice": "af_heart"}' \
  --output speech.wav
```

Response headers include `X-Audio-Duration`, `X-Sample-Rate`, and `X-Voice`.

### Batch processing

```bash
curl -X POST http://localhost:8880/v1/audio/batch \
  -H "Content-Type: application/json" \
  -d '{"items": [
    {"input": "First sentence", "voice": "af_heart"},
    {"input": "Second sentence", "voice": "am_adam"}
  ]}'
```

Returns a `job_id` to poll with `GET /v1/audio/batch/{job_id}`.

### Other endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /` | Web UI |
| `GET /health` | Health check |
| `GET /stats` | System and TTS metrics |
| `GET /voices` | Available voices |
| `GET /languages` | Supported languages |
| `GET /cache` | Browse cached audio |
| `GET /logs` | Request logs |
| `GET /generations` | Generation history |

## Request Parameters

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `input` | string | (required) | Text to synthesize (1-10,000 chars) |
| `voice` | string | `af_heart` | Voice ID |
| `speed` | float | `1.0` | Playback speed |
| `lang_code` | string | `a` | Language code |

## Available Voices

54 voices across 9 languages. Examples:

| Voice ID | Description |
|----------|-------------|
| af_heart | American Female - Heart (default) |
| af_bella | American Female - Bella |
| af_sarah | American Female - Sarah |
| am_adam | American Male - Adam |
| am_michael | American Male - Michael |
| bf_emma | British Female - Emma |
| bm_george | British Male - George |

Full list at `GET /voices` or [VOICES.md](https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md).

## Language Codes

| Code | Language |
|------|----------|
| a | American English |
| b | British English |
| j | Japanese |
| z | Mandarin Chinese |
| e | Spanish |
| f | French |
| h | Hindi |
| i | Italian |
| p | Brazilian Portuguese |

## Shell Client

`speak.sh` sends text to the server and plays audio through your speakers:

```bash
./speak.sh "Hello world"
./speak.sh "Hello world" am_adam
echo "Hello world" | ./speak.sh -
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MONGO_URL` | `mongodb://localhost:27017` | MongoDB connection string |
| `MONGO_DB` | `kokoro` | Database name |
| `AUDIO_CACHE_DIR` | `/app/audio_cache` | Cache directory path |
| `HF_HUB_DOWNLOAD_TIMEOUT` | `120` | HuggingFace download timeout (seconds) |

### Cache Settings

Configurable via `PUT /settings/cache` or the web UI:

- Min/max text length for caching
- Max audio duration, file size, total cache size
- Max entries and TTL (days)

## Resources

- [Model Card](https://huggingface.co/hexgrad/Kokoro-82M)
- [GitHub (upstream)](https://github.com/hexgrad/kokoro)
- [Voice List](https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md)
- [Demo](https://hf.co/spaces/hexgrad/Kokoro-TTS)

## License

Kokoro-82M is released under the Apache 2.0 license.
