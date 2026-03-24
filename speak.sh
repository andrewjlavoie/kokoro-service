#!/usr/bin/env bash
# Usage: ./speak.sh "Text to speak" [voice]
#    or: echo "text" | ./speak.sh - [voice]
#    or: (hook mode) reads last_assistant_message from stdin JSON
# Sends text to the Kokoro TTS server and plays it through speakers.

set -euo pipefail

VOICE="${2:-af_heart}"
SERVER="${KOKORO_TTS_URL:-http://localhost:8880}"

# Get text from argument, stdin JSON (hook mode), or plain stdin
if [[ "${1:-}" == "--hook" ]]; then
  # Hook mode: read JSON from stdin, extract last_assistant_message, strip code blocks
  TEXT=$(jq -r '.last_assistant_message // empty' | sed '/^```/,/^```$/d' | sed '/^[[:space:]]*$/d')
elif [[ "${1:-}" == "-" ]]; then
  TEXT=$(cat)
elif [[ -n "${1:-}" ]]; then
  TEXT="$1"
else
  echo "Usage: speak.sh \"text\" [voice]" >&2
  exit 1
fi

if [[ -z "$TEXT" ]]; then
  exit 0
fi

TMPFILE=$(mktemp /tmp/kokoro-XXXXXX.wav)
trap 'rm -f "$TMPFILE"' EXIT

curl -sf -X POST "${SERVER}/synthesize" \
  -H "Content-Type: application/json" \
  -d "$(jq -n --arg t "$TEXT" --arg v "$VOICE" '{input: $t, voice: $v}')" \
  -o "$TMPFILE"

# Play with whatever's available
if command -v pw-play &>/dev/null; then
  pw-play "$TMPFILE"
elif command -v aplay &>/dev/null; then
  aplay -q "$TMPFILE"
elif command -v ffplay &>/dev/null; then
  ffplay -nodisp -autoexit -loglevel quiet "$TMPFILE"
fi
