# Kokoro TTS - Tribal Knowledge

Hard-won lessons from standing up Kokoro-82M on Fedora Linux 43.

## System Context

- **OS**: Fedora Linux 43
- **CPU**: AMD Ryzen AI MAX+ 395 (32 cores @ 5.19 GHz)
- **GPU**: AMD Radeon 8060S (integrated) — CUDA not available, runs on CPU only
- **RAM**: 125GB
- **System Python**: 3.14 (too new for kokoro)

## Gotcha #1: Python Version Constraint

Kokoro requires **Python 3.10-3.12**. Fedora 43 ships Python 3.14, which is incompatible. The workaround is to use `uv` to create a venv pinned to 3.12:

```bash
uv venv --python 3.12 venv
```

This downloads and manages a separate Python 3.12 installation automatically.

## Gotcha #2: uv Venvs Don't Include pip

This is the sneakiest issue. When you create a venv with `uv venv`, it does **not** include `pip`. This matters because:

- The `misaki` G2P library (used by kokoro) needs the spaCy model `en_core_web_sm`
- On first run, it tries to auto-download it via `spacy.cli.download()`, which calls `pip` internally
- With no `pip` in the venv, this **silently crashes** with exit code 1 and the message `/path/to/python: No module named pip`
- There is no traceback, no helpful error — just a dead process

**Fix**: Install the spaCy model directly with `uv pip`:

```bash
source venv/bin/activate
uv pip install en_core_web_sm@https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl
```

If you ever see `No module named pip` in the output, this is the pattern: something tried to use pip in a uv-created venv. Use `uv pip install` instead.

## Gotcha #3: HuggingFace Download Timeouts

The `huggingface_hub` library has a **10-second default read timeout**. On first run, kokoro needs to download:

| File | Size | Notes |
|------|------|-------|
| `config.json` | ~2KB | Model configuration |
| `kokoro-v1_0.pth` | ~312MB | Model weights |
| `voices/af_heart.pt` | ~few KB | Voice embedding (one per voice) |

The model weights can take a while. If downloads time out, set a longer timeout:

```bash
HF_HUB_DOWNLOAD_TIMEOUT=120 python tts.py "Hello world"
```

Files are cached in `~/.cache/huggingface/hub/models--hexgrad--Kokoro-82M/`. Once downloaded, subsequent runs are fast.

## Gotcha #4: espeak-ng is a System Dependency

Kokoro uses `espeak-ng` for phoneme conversion. It must be installed at the system level — it's not a Python package:

```bash
sudo dnf install espeak-ng    # Fedora/RHEL
sudo apt install espeak-ng    # Ubuntu/Debian
```

Without it, you'll get an error about `EspeakFallback` during pipeline initialization.

## Gotcha #5: Torch Warnings Are Harmless

Every run prints these warnings — they're safe to ignore:

```
UserWarning: dropout option adds dropout after all but last recurrent layer...
FutureWarning: `torch.nn.utils.weight_norm` is deprecated...
```

The `WARNING: Defaulting repo_id to hexgrad/Kokoro-82M` is also harmless. Suppress it by passing `repo_id='hexgrad/Kokoro-82M'` explicitly to `KPipeline`.

## Complete Setup From Scratch

```bash
# 1. System dependency
sudo dnf install espeak-ng

# 2. Create Python 3.12 venv (uv handles the Python install)
cd /home/andrew/Code/projects/kokoro
uv venv --python 3.12 venv
source venv/bin/activate

# 3. Install Python packages
uv pip install kokoro soundfile torch

# 4. Install spaCy model (MUST do this — won't auto-install without pip)
uv pip install en_core_web_sm@https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl

# 5. First run (downloads ~312MB of model weights from HuggingFace)
HF_HUB_DOWNLOAD_TIMEOUT=120 python tts.py "Hello world, this is Kokoro text to speech!"

# 6. Output is in output/output_000.wav
aplay output/output_000.wav
```

## Quick Reference

| Command | What it does |
|---------|-------------|
| `python tts.py "text"` | Generate speech with default voice (af_heart) |
| `python tts.py "text" --voice am_adam` | Use a specific voice |
| `python tts.py --list-voices` | Show available voices |
| `python tts.py --file input.txt` | Read text from file |
| `python -m kokoro -t "text" -o out.wav` | Built-in kokoro CLI |

## Why Kokoro?

Evaluated against other open-source TTS options as of early 2026:

| Model | Params | Quality | Speed (CPU) | License | Notes |
|-------|--------|---------|-------------|---------|-------|
| **Kokoro-82M** | 82M | High | Fast | Apache 2.0 | Best balance of quality/simplicity |
| Coqui XTTS | ~400M | Very high | Slow | MPL 2.0 | Voice cloning, but company shut down |
| Piper | Varies | Medium | Very fast | MIT | Great for embedded/edge |
| F5-TTS | ~300M | Very high | Medium | CC-BY-NC | Complex setup, non-commercial license |
| Parler-TTS | ~800M | High | Slow | Apache 2.0 | Descriptive voice control |

Kokoro hits the sweet spot: small enough to run fast on CPU, high enough quality for production use, simple pip install, Apache 2.0 licensed.
