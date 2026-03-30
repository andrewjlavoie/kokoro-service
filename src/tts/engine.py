"""Kokoro TTS engine — wraps KPipeline with a simple two-method API."""

import shutil
import subprocess
import tempfile
from collections.abc import Generator
from pathlib import Path

import numpy as np
import soundfile as sf
from kokoro import KPipeline

from src.tts.constants import LANGUAGE_CODES, SAMPLE_RATE, VOICES


class KokoroTTS:
    """Text-to-speech with a two-method API: say() and synthesize()."""

    def __init__(self, voice: str = "af_heart", lang_code: str = "a", speed: float = 1.0):
        self.voice = voice
        self.lang_code = lang_code
        self.speed = speed
        self._pipeline = None

    @staticmethod
    def list_voices() -> dict[str, str]:
        """Return available voice IDs and their descriptions."""
        return dict(VOICES)

    @staticmethod
    def list_languages() -> dict[str, str]:
        """Return available language codes and their descriptions."""
        return dict(LANGUAGE_CODES)

    @property
    def is_loaded(self) -> bool:
        """Whether the TTS pipeline is loaded and ready."""
        return self._pipeline is not None

    def ensure_pipeline(self, lang_code: str | None = None):
        """Load or switch the language pipeline. Raises RuntimeError on failure."""
        lang = lang_code or self.lang_code
        if self._pipeline is None or lang != self.lang_code:
            self.lang_code = lang
            try:
                self._pipeline = KPipeline(lang_code=lang, repo_id="hexgrad/Kokoro-82M")
            except (ImportError, ModuleNotFoundError) as e:
                lang_name = LANGUAGE_CODES.get(lang, lang)
                raise RuntimeError(f"Language '{lang_name}' requires additional dependencies: {e}") from e
            except AssertionError:
                raise RuntimeError(f"Language code '{lang}' is not supported by the model") from None

    def synthesize_stream(
        self, text: str, voice: str | None = None, speed: float | None = None, lang_code: str | None = None,
    ) -> Generator[np.ndarray, None, None]:
        """Yield audio segments as they are generated (numpy float32 arrays)."""
        self.ensure_pipeline(lang_code)
        voice = voice or self.voice
        speed = speed or self.speed
        for _, _, audio in self._pipeline(text, voice=voice, speed=speed):
            yield audio.numpy() if hasattr(audio, "numpy") else np.asarray(audio)

    def synthesize(self, text: str, voice: str | None = None, speed: float | None = None, lang_code: str | None = None) -> tuple[np.ndarray, int]:
        """Convert text to audio. Returns (numpy_array, sample_rate)."""
        chunks = list(self.synthesize_stream(text, voice=voice, speed=speed, lang_code=lang_code))
        if not chunks:
            return np.array([], dtype=np.float32), SAMPLE_RATE
        return np.concatenate(chunks), SAMPLE_RATE

    def say(self, text: str, voice: str | None = None, speed: float | None = None, lang_code: str | None = None) -> None:
        """Synthesize text and play it through speakers."""
        audio, sr = self.synthesize(text, voice=voice, speed=speed, lang_code=lang_code)
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
