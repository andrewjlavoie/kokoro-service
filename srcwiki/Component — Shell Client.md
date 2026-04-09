# Component — Shell Client

#component #cli

**Location:** `speak.sh`

## Purpose

A bash script that sends text to the Kokoro TTS server and plays the resulting audio through the local system's speakers. Used for quick command-line TTS without a browser.

## Usage

```bash
# Direct text
./speak.sh "Hello world"

# With specific voice
./speak.sh "Hello world" am_adam

# Pipe from stdin
echo "Hello world" | ./speak.sh -

# Hook mode (reads JSON from stdin)
echo '{"last_assistant_message":"Hello"}' | ./speak.sh --hook
```

## Modes

### 1. Direct Argument
```bash
./speak.sh "Text to speak" [voice]
```

### 2. Stdin Mode
```bash
echo "text" | ./speak.sh - [voice]
```
Reads plain text from stdin when first argument is `-`.

### 3. Hook Mode
```bash
echo '{"last_assistant_message":"Hello"}' | ./speak.sh --hook
```
Designed for integration with Claude Code's Stop hooks. Reads JSON from stdin, extracts `last_assistant_message`, strips code blocks (` ``` ` fences), and removes blank lines before sending to TTS.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `KOKORO_TTS_URL` | `http://localhost:8880` | TTS server URL (environment variable) |
| Second argument | `af_heart` | Voice ID |

## Implementation Details

1. **Text extraction**: Depending on mode, text is read from argument, piped stdin, or parsed from JSON via `jq`
2. **Empty check**: Exits silently if text is empty (e.g., code-only responses in hook mode)
3. **Synthesis**: Sends `POST /synthesize` with JSON body `{input, voice}` via `curl`
4. **Temporary file**: Audio saved to `/tmp/kokoro-XXXXXX.wav` with `trap` cleanup on exit
5. **Playback**: Tries players in order: `pw-play` (PipeWire), `aplay` (ALSA), `ffplay` (FFmpeg)

## Dependencies

| Tool | Purpose | Required |
|------|---------|----------|
| `curl` | HTTP client | Yes |
| `jq` | JSON construction and parsing | Yes |
| `pw-play` / `aplay` / `ffplay` | Audio playback | At least one |

## Related Pages

- [[API — Speech Endpoints]] — The `/synthesize` endpoint this script calls
- [[User Flows]] — CLI usage scenarios
- [[Setup and Installation]] — Audio player setup
