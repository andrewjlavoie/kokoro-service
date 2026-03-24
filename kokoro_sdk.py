"""Minimal Kokoro TTS SDK for AI agent integration."""

import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf
from kokoro import KPipeline

SAMPLE_RATE = 24000


class KokoroTTS:
    """Text-to-speech with a two-method API: say() and synthesize()."""

    def __init__(self, voice: str = "af_heart", lang_code: str = "a", speed: float = 1.0):
        self.voice = voice
        self.lang_code = lang_code
        self.speed = speed
        self._pipeline = None

    def _ensure_pipeline(self):
        if self._pipeline is None:
            self._pipeline = KPipeline(lang_code=self.lang_code, repo_id="hexgrad/Kokoro-82M")

    def synthesize(self, text: str, voice: str | None = None, speed: float | None = None) -> tuple[np.ndarray, int]:
        """Convert text to audio. Returns (numpy_array, sample_rate)."""
        self._ensure_pipeline()
        voice = voice or self.voice
        speed = speed or self.speed
        chunks = []
        for _, _, audio in self._pipeline(text, voice=voice, speed=speed):
            chunks.append(audio)
        if not chunks:
            return np.array([], dtype=np.float32), SAMPLE_RATE
        return np.concatenate(chunks), SAMPLE_RATE

    def say(self, text: str, voice: str | None = None, speed: float | None = None) -> None:
        """Synthesize text and play it through speakers."""
        audio, sr = self.synthesize(text, voice=voice, speed=speed)
        if len(audio) == 0:
            return
        player = _find_player()
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            sf.write(f.name, audio, sr)
            tmp = f.name
        try:
            subprocess.run([player, tmp], check=True, capture_output=True)
        finally:
            Path(tmp).unlink(missing_ok=True)


def _find_player() -> str:
    for cmd in ("pw-play", "aplay", "paplay", "ffplay"):
        if shutil.which(cmd):
            return cmd
    raise RuntimeError("No audio player found. Install pipewire, alsa-utils, or ffmpeg.")
