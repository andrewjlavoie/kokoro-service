# Kokoro TTS - Getting Started

A simple setup for running [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M), an open-weight text-to-speech model with 82 million parameters.

## System Requirements

- **Python 3.10-3.12** (kokoro does not yet support Python 3.13+)
- ~500MB disk space for model weights
- Works on CPU (GPU optional but faster)

Tested on:
- Fedora Linux 43
- AMD Ryzen AI MAX+ 395 (32 cores)
- 125GB RAM

## Quick Start

### 1. Install system dependency

Kokoro requires `espeak-ng` for phoneme conversion:

```bash
# Fedora/RHEL
sudo dnf install espeak-ng

# Ubuntu/Debian
sudo apt install espeak-ng

# Arch
sudo pacman -S espeak-ng
```

### 2. Create virtual environment

Using `uv` (recommended if you have Python 3.13+):

```bash
cd /home/andrew/Code/projects/kokoro
uv venv --python 3.12 venv
source venv/bin/activate
```

Or with standard Python 3.10-3.12:

```bash
cd /home/andrew/Code/projects/kokoro
python3.12 -m venv venv
source venv/bin/activate
```

### 3. Install Python dependencies

```bash
# Using uv (faster)
uv pip install kokoro soundfile torch

# Or using pip
pip install -r requirements.txt
```

**Note:** The first run will download model weights (~312MB) and voice files from HuggingFace. This may take several minutes depending on your internet connection.

### 4. Generate speech

```bash
# Basic usage
python tts.py "Hello, this is Kokoro text to speech!"

# Use a different voice
python tts.py "Hello world" --voice am_adam

# Read from file
python tts.py --file input.txt --output my_audio

# List available voices
python tts.py --list-voices
```

Output files are saved to `output/` directory by default.

## Available Voices

The model includes 54 voices across 8 languages. Here are some examples:

| Voice ID | Description |
|----------|-------------|
| af_heart | American Female - Heart (default) |
| af_bella | American Female - Bella |
| af_sarah | American Female - Sarah |
| am_adam | American Male - Adam |
| am_michael | American Male - Michael |
| bf_emma | British Female - Emma |
| bm_george | British Male - George |

Run `python tts.py --list-voices` for more options.

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
| k | Korean |

## Usage Examples

```bash
# American English (default)
python tts.py "Hello world"

# British English
python tts.py "Hello world" --lang b --voice bf_emma

# French
python tts.py "Bonjour le monde" --lang f

# Japanese
python tts.py "こんにちは世界" --lang j
```

## Python API

```python
from kokoro import KPipeline
import soundfile as sf

# Initialize pipeline
pipeline = KPipeline(lang_code='a')

# Generate speech
text = "Hello, this is a test of Kokoro text to speech."
generator = pipeline(text, voice='af_heart')

for i, (graphemes, phonemes, audio) in enumerate(generator):
    sf.write(f'output_{i}.wav', audio, 24000)
```

## Resources

- [Model Card](https://huggingface.co/hexgrad/Kokoro-82M)
- [GitHub](https://github.com/hexgrad/kokoro)
- [Voice List](https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md)
- [Demo](https://hf.co/spaces/hexgrad/Kokoro-TTS)

## License

Kokoro-82M is released under the Apache 2.0 license.
