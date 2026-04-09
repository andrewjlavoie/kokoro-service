# User Flows

#userflow

End-to-end scenarios showing how users interact with the Kokoro TTS Service.

---

## Flow 1: Basic Text-to-Speech via curl

**Scenario:** A developer wants to convert text to speech and save it as a WAV file.

### Steps

1. **Send request:**
   ```bash
   curl -X POST http://localhost:8880/synthesize \
     -H "Content-Type: application/json" \
     -d '{"input": "Welcome to our application", "voice": "af_heart"}' \
     --output welcome.wav
   ```

2. **Server processing:**
   - Middleware assigns request ID and starts timer
   - Pydantic validates the request (26 chars, within 1-10000 limit)
   - Cache lookup: SHA-256 of `"Welcome to our application|af_heart|1.0|a"` → miss
   - `ensure_pipeline("a")` — pipeline already loaded (American English)
   - `tts.synthesize()` → ~500ms on CPU → numpy array + 24000 Hz
   - Encode to WAV via soundfile
   - Background: persist log, persist generation, store in cache

3. **Response:**
   ```
   HTTP/1.1 200 OK
   Content-Type: audio/wav
   X-Request-ID: a1b2c3d4
   X-Audio-Duration: 1.87
   X-Sample-Rate: 24000
   X-Voice: af_heart

   [WAV binary data]
   ```

4. **Second identical request:**
   - Cache lookup → hit (SHA-256 matches)
   - Return cached WAV instantly (~2ms vs ~500ms)
   - Response includes `X-Cache: hit` header

### Expected Output
- `welcome.wav` — 1.87 second WAV file, PCM 16-bit mono, 24000 Hz

---

## Flow 2: OpenAI-Compatible Integration

**Scenario:** An application that uses the OpenAI TTS API switches to local inference.

### Steps

1. **Change base URL** in your OpenAI client:
   ```python
   # Before: OpenAI cloud
   # client = OpenAI()
   # After: Local Kokoro
   import httpx
   response = httpx.post(
       "http://localhost:8880/v1/audio/speech",
       json={"input": "Hello from local TTS", "voice": "af_heart"}
   )
   with open("output.wav", "wb") as f:
       f.write(response.content)
   ```

2. **Streaming playback** (e.g., with audio player):
   ```bash
   curl -N -X POST http://localhost:8880/v1/audio/speech \
     -H "Content-Type: application/json" \
     -d '{"input": "This streams as it generates"}' | aplay
   ```

### Notes
- The request body shape matches `POST /v1/audio/speech` from OpenAI
- Voice IDs differ (Kokoro uses `af_heart`, `am_adam`, etc. instead of `alloy`, `echo`, etc.)
- Response is WAV format (OpenAI returns MP3 by default)

---

## Flow 3: Batch Processing for Audiobook Generation

**Scenario:** Convert multiple paragraphs to speech in one request.

### Steps

1. **Submit batch:**
   ```bash
   curl -X POST http://localhost:8880/v1/audio/batch \
     -H "Content-Type: application/json" \
     -d '{
       "items": [
         {"input": "Chapter one. It was a dark and stormy night.", "voice": "bf_emma"},
         {"input": "The wind howled through the empty streets.", "voice": "bf_emma"},
         {"input": "Not a soul dared venture outside.", "voice": "bf_emma"}
       ]
     }'
   ```

   Response:
   ```json
   {"job_id": "a1b2c3d4-...", "status": "pending", "total_items": 3}
   ```

2. **Poll for completion:**
   ```bash
   curl http://localhost:8880/v1/audio/batch/a1b2c3d4-...
   ```

   Response (while processing):
   ```json
   {"job_id": "...", "status": "processing", "completed_items": 1, "failed_items": 0, ...}
   ```

   Response (complete):
   ```json
   {"job_id": "...", "status": "completed", "completed_items": 3, "failed_items": 0,
    "items": [
      {"index": 0, "status": "completed", "cache_id": "507f...", "audio_duration_sec": 3.2},
      {"index": 1, "status": "completed", "cache_id": "508f...", "audio_duration_sec": 2.8},
      {"index": 2, "status": "completed", "cache_id": "509f...", "audio_duration_sec": 2.1}
    ]}
   ```

3. **Download each audio file:**
   ```bash
   curl http://localhost:8880/cache/507f... --output chapter1_p1.wav
   curl http://localhost:8880/cache/508f... --output chapter1_p2.wav
   curl http://localhost:8880/cache/509f... --output chapter1_p3.wav
   ```

---

## Flow 4: Shell Client for Quick TTS

**Scenario:** A developer wants to hear text spoken through their speakers.

### Steps

```bash
# Direct text
./speak.sh "Build succeeded with zero warnings"

# Different voice
./speak.sh "Build succeeded with zero warnings" am_adam

# Pipe from another command
echo "Deploy complete" | ./speak.sh -
```

### Hook Mode (Claude Code Integration)

When configured as a Claude Code Stop hook, `speak.sh` automatically reads Claude's last response and speaks it:

```bash
# In .claude/settings.local.json:
# "hooks": { "Stop": [{ "command": "./speak.sh --hook" }] }

# Claude responds with "I've fixed the bug"
# → Hook receives JSON: {"last_assistant_message": "I've fixed the bug"}
# → speak.sh extracts text, sends to server, plays audio
```

> [!TIP]
> Code blocks (` ``` ` fences) are automatically stripped in hook mode so code isn't spoken aloud.

---

## Flow 5: Cache Management via Web UI

**Scenario:** An administrator reviews and organizes cached audio.

### Steps

1. **Open dashboard:** Navigate to `http://localhost:8880/`
2. **Browse cache:** View all cached entries with text previews, durations, hit counts
3. **Search:** Use the search box to find specific cached text
4. **Filter:** Filter by voice, language, or tag
5. **Tag entries:** Add tags like "production", "demo", "greetings" to organize
6. **Play audio:** Click to download and play cached audio files
7. **Delete:** Remove unwanted entries (deletes both metadata and WAV file)
8. **Adjust settings:** Change TTL, max entries, size limits via the settings panel
9. **TTL cleanup:** Trigger manual cleanup of expired entries

---

## Flow 6: Monitoring and Debugging

**Scenario:** Investigating why a synthesis request was slow.

### Steps

1. **Check health:** `GET /health` — verify model is loaded
2. **View stats:** `GET /stats` — check CPU/memory usage and average synthesis time
3. **Search logs:** `GET /logs?search=abc12345` — find logs for a specific request ID
4. **View generations:** `GET /generations` — see synthesis history with timing data
5. **Live logs:** Connect to `ws://localhost:8880/ws/logs` for real-time event stream

### Error Handling and Edge Cases

| Situation | Behavior |
|-----------|----------|
| Empty input | 422 validation error |
| Input > 10,000 chars | 422 validation error |
| Unknown voice ID | Model attempts synthesis (may produce degraded output) |
| Unknown language code | 400 with "not supported by the model" message |
| Model not loaded yet | 503 "Model not loaded" |
| MongoDB down | Synthesis works; caching/persistence disabled |
| Batch with 0 items | 422 validation error |
| Batch with > 100 items | 422 validation error |
| Cache at max entries | New entries not cached; synthesis still works |

## Related Pages

- [[API — Speech Endpoints]] — Endpoint specifications
- [[API — Batch Endpoints]] — Batch processing details
- [[API — Cache Endpoints]] — Cache CRUD
- [[Component — Shell Client]] — speak.sh details
