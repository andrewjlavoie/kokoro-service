# API — Speech Endpoints

#api #speech

**File:** `src/api/speech.py`

The two core synthesis endpoints. Both accept the same request body but differ in response behavior.

---

## POST `/v1/audio/speech`

**OpenAI-compatible streaming TTS endpoint.**

Streams WAV audio as segments are generated. The first audio bytes arrive before synthesis completes, reducing perceived latency.

### Request

```bash
curl -X POST http://localhost:8880/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"input": "Hello world", "voice": "af_heart", "speed": 1.0, "lang_code": "a"}' \
  --output speech.wav
```

### Request Body

| Field | Type | Required | Default | Constraints | Description |
|-------|------|----------|---------|-------------|-------------|
| `input` | string | Yes | — | 1-10,000 chars | Text to synthesize |
| `voice` | string | No | `"af_heart"` | Valid voice ID | Voice to use |
| `speed` | float | No | `1.0` | — | Playback speed multiplier |
| `lang_code` | string | No | `"a"` | Valid language code | Language for phonemization |

### Response

| Header | Description |
|--------|-------------|
| `Content-Type` | `audio/wav` |
| `X-Request-ID` | Unique request identifier (8 chars) |
| `X-Cache` | `"hit"` if served from cache |

**Body:** Streaming WAV audio (PCM 16-bit mono, 24000 Hz)

### Cache Behavior
- On cache hit: returns complete WAV immediately (not streamed)
- On cache miss: streams audio segments, then stores complete WAV in cache via background task

### Error Responses

| Status | Condition |
|--------|-----------|
| 400 | Unsupported language code |
| 422 | Validation error (empty input, input too long) |
| 503 | Model not loaded |

---

## POST `/synthesize`

**Full WAV synthesis with metadata headers.**

Waits for complete synthesis before returning. Includes audio metadata in response headers.

### Request

```bash
curl -X POST http://localhost:8880/synthesize \
  -H "Content-Type: application/json" \
  -d '{"input": "Hello world", "voice": "af_heart"}' \
  --output speech.wav
```

### Request Body

Same as `/v1/audio/speech` (see above).

### Response

| Header | Value | Description |
|--------|-------|-------------|
| `Content-Type` | `audio/wav` | |
| `X-Request-ID` | `abc12345` | Unique request identifier |
| `X-Audio-Duration` | `1.23` | Audio length in seconds |
| `X-Sample-Rate` | `24000` | Sample rate in Hz |
| `X-Voice` | `af_heart` | Voice ID used |
| `X-Cache` | `hit` | Present only on cache hits |

**Body:** Complete WAV file (PCM 16-bit mono, 24000 Hz)

### Error Responses

| Status | Condition |
|--------|-----------|
| 400 | Unsupported language / no audio generated |
| 422 | Validation error |
| 503 | Model not loaded |

---

## Choosing Between Endpoints

| Criterion | `/v1/audio/speech` | `/synthesize` |
|-----------|-------------------|---------------|
| OpenAI API compatible | Yes | No |
| First byte latency | Low (streaming) | Higher (waits for full) |
| Audio metadata headers | No | Yes |
| WAV header accuracy | Unknown-length marker | Correct file size |
| Best for | Real-time playback | File generation, metadata needed |

## Related Pages

- [[Component — API Layer]] — Implementation details
- [[Component — Cache Manager]] — Cache lookup and store
- [[Data Flow]] — Full request lifecycle
- [[User Flows]] — End-to-end examples
