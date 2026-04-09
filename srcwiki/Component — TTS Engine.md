# Component — TTS Engine

#component #tts

**Location:** `src/tts/`
**Files:** `engine.py`, `constants.py`, `__init__.py`

## Purpose

Wraps the upstream `kokoro` library's `KPipeline` with a simplified two-method API (`say` and `synthesize`). The engine manages pipeline lifecycle (loading, language switching) and provides a `say()` method for local audio playback.

## Class: `KokoroTTS`

**File:** `src/tts/engine.py`

### Constructor

```python
KokoroTTS(voice="af_heart", lang_code="a", speed=1.0)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `voice` | str | `"af_heart"` | Default voice ID |
| `lang_code` | str | `"a"` | Default language code |
| `speed` | float | `1.0` | Default playback speed multiplier |

The constructor does **not** load the model. The pipeline is loaded lazily on first call to `ensure_pipeline()` or any synthesis method.

### Methods

#### `ensure_pipeline(lang_code=None)`
Loads or switches the KPipeline for the given language. Called automatically by synthesis methods but can be called explicitly to force-load at startup.

- If `self._pipeline is None` or the requested language differs from the current one, creates a new `KPipeline(lang_code=lang, repo_id="hexgrad/Kokoro-82M")`.
- On first call, downloads model weights (~312MB) from HuggingFace.
- Raises `RuntimeError` if the language requires missing dependencies (e.g., Japanese needs `pyopenjtalk`) or is unsupported.

#### `synthesize(text, voice=None, speed=None, lang_code=None) -> tuple[np.ndarray, int]`
Converts text to a complete audio array. Internally calls `synthesize_stream()` and concatenates all segments.

Returns `(audio_array, sample_rate)` where:
- `audio_array` is a numpy float32 array (values in [-1.0, 1.0])
- `sample_rate` is always `24000`

Returns `(empty_array, 24000)` if the model produces no output.

#### `synthesize_stream(text, voice=None, speed=None, lang_code=None) -> Generator[np.ndarray]`
Yields audio segments as they are generated. Each segment is a numpy float32 array. This is the core synthesis method — `synthesize()` and `say()` both build on it.

The underlying `KPipeline.__call__()` returns `(graphemes, phonemes, audio)` tuples; only the audio is yielded.

#### `say(text, voice=None, speed=None, lang_code=None) -> None`
Synthesizes text and plays it through the system's audio output. Used for local/CLI playback, not for the HTTP API.

1. Calls `synthesize()` to get audio
2. Writes to a temporary WAV file via `soundfile`
3. Plays with the first available player: `pw-play`, `aplay`, `paplay`, or `ffplay`
4. Cleans up the temporary file

#### `list_voices() -> dict[str, str]` (static)
Returns the `VOICES` dictionary mapping voice IDs to descriptions.

#### `list_languages() -> dict[str, str]` (static)
Returns the `LANGUAGE_CODES` dictionary mapping codes to language names.

#### `is_loaded -> bool` (property)
Returns `True` if `self._pipeline is not None`.

## Constants (`src/tts/constants.py`)

### `SAMPLE_RATE = 24000`
All audio produced by Kokoro-82M is at 24,000 Hz.

### `VOICES`
Dictionary of 11 voice IDs and their human-readable names:

| Voice ID | Description |
|----------|-------------|
| `af_heart` | American Female - Heart (default) |
| `af_bella` | American Female - Bella |
| `af_nicole` | American Female - Nicole |
| `af_sarah` | American Female - Sarah |
| `af_sky` | American Female - Sky |
| `am_adam` | American Male - Adam |
| `am_michael` | American Male - Michael |
| `bf_emma` | British Female - Emma |
| `bf_isabella` | British Female - Isabella |
| `bm_george` | British Male - George |
| `bm_lewis` | British Male - Lewis |

> [!NOTE]
> The upstream Kokoro-82M model supports 54 voices. The `VOICES` dict here contains a curated subset. The full list is available at the model's [VOICES.md](https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md). Any valid voice ID accepted by KPipeline will work even if not listed here.

### `LANGUAGE_CODES`

| Code | Language |
|------|----------|
| `a` | American English |
| `b` | British English |
| `j` | Japanese |
| `z` | Mandarin Chinese |
| `e` | Spanish |
| `f` | French |
| `h` | Hindi |
| `i` | Italian |
| `p` | Brazilian Portuguese |

## Dependencies

| Dependency | Purpose |
|-----------|---------|
| `kokoro` (>=0.9.2) | KPipeline — the core TTS inference library |
| `numpy` | Audio array manipulation |
| `soundfile` | WAV encoding (used in `say()`) |
| `espeak-ng` (system) | Phoneme conversion for English, Spanish, French, Hindi, Italian, Portuguese |
| `misaki[ja]` | Japanese phonemizer (requires `pyopenjtalk`, `unidic`) |
| `misaki[zh]` | Mandarin Chinese phonemizer |

## Pipeline Loading Behavior

```
First request with lang_code="a":
  1. KPipeline downloads hexgrad/Kokoro-82M from HuggingFace (~312MB)
  2. Model loaded into CPU memory
  3. Pipeline stored in self._pipeline

Subsequent request with lang_code="a":
  → Reuses existing pipeline (no overhead)

Request with lang_code="j":
  1. New KPipeline created for Japanese
  2. Old pipeline garbage collected
  3. self.lang_code updated to "j"
```

> [!WARNING]
> Switching languages replaces the pipeline entirely. If your workload alternates between languages frequently, expect re-initialization overhead on each switch. In practice, most deployments serve a single language.

## Related Pages

- [[Component — API Layer]] — How the API calls the engine
- [[Data Flow]] — Text-to-audio transformation pipeline
- [[Architecture]] — Where the engine fits in the system
