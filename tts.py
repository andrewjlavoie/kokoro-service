#!/usr/bin/env python3
"""
Kokoro TTS - Text-to-Speech Generator

A simple script to generate speech from text using the Kokoro-82M model.
"""

import argparse
import sys
from pathlib import Path

import soundfile as sf
from kokoro import KPipeline


# Language codes and their descriptions
LANGUAGE_CODES = {
    'a': 'American English',
    'b': 'British English',
    'j': 'Japanese',
    'z': 'Mandarin Chinese',
    'e': 'Spanish',
    'f': 'French',
    'h': 'Hindi',
    'i': 'Italian',
    'p': 'Brazilian Portuguese',
}

# Popular voices (see VOICES.md for full list)
EXAMPLE_VOICES = {
    'af_heart': 'American Female - Heart (default)',
    'af_bella': 'American Female - Bella',
    'af_nicole': 'American Female - Nicole',
    'af_sarah': 'American Female - Sarah',
    'af_sky': 'American Female - Sky',
    'am_adam': 'American Male - Adam',
    'am_michael': 'American Male - Michael',
    'bf_emma': 'British Female - Emma',
    'bf_isabella': 'British Female - Isabella',
    'bm_george': 'British Male - George',
    'bm_lewis': 'British Male - Lewis',
}


def generate_speech(
    text: str,
    voice: str = 'af_heart',
    lang_code: str = 'a',
    output_dir: str = 'output',
    sample_rate: int = 24000,
) -> list[Path]:
    """
    Generate speech from text using Kokoro TTS.

    Args:
        text: The text to convert to speech
        voice: Voice ID to use (e.g., 'af_heart', 'am_adam')
        lang_code: Language code ('a' for American English, etc.)
        output_dir: Directory to save output files
        sample_rate: Audio sample rate (default 24000)

    Returns:
        List of paths to generated audio files
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    print(f"Initializing Kokoro pipeline (lang={lang_code})...")
    pipeline = KPipeline(lang_code=lang_code)

    print(f"Generating speech with voice '{voice}'...")
    generator = pipeline(text, voice=voice)

    output_files = []
    for i, (graphemes, phonemes, audio) in enumerate(generator):
        output_file = output_path / f"output_{i:03d}.wav"
        sf.write(str(output_file), audio, sample_rate)
        print(f"  Segment {i}: {graphemes[:50]}..." if len(graphemes) > 50 else f"  Segment {i}: {graphemes}")
        output_files.append(output_file)

    print(f"\nGenerated {len(output_files)} audio file(s) in '{output_dir}/'")
    return output_files


def main():
    parser = argparse.ArgumentParser(
        description='Generate speech from text using Kokoro-82M TTS',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f'''
Example voices:
{chr(10).join(f"  {k}: {v}" for k, v in EXAMPLE_VOICES.items())}

Language codes:
{chr(10).join(f"  {k}: {v}" for k, v in LANGUAGE_CODES.items())}

Examples:
  python tts.py "Hello, world!"
  python tts.py "Hello, world!" --voice am_adam
  python tts.py --file input.txt --output speeches
  python tts.py "Bonjour le monde!" --lang f --voice ff_siwis
'''
    )

    parser.add_argument('text', nargs='?', help='Text to convert to speech')
    parser.add_argument('--file', '-f', help='Read text from file instead')
    parser.add_argument('--voice', '-v', default='af_heart', help='Voice ID (default: af_heart)')
    parser.add_argument('--lang', '-l', default='a', choices=LANGUAGE_CODES.keys(),
                        help='Language code (default: a for American English)')
    parser.add_argument('--output', '-o', default='output', help='Output directory (default: output)')
    parser.add_argument('--list-voices', action='store_true', help='List example voices and exit')

    args = parser.parse_args()

    if args.list_voices:
        print("Example voices (see VOICES.md for full list of 54 voices):\n")
        for voice_id, description in EXAMPLE_VOICES.items():
            print(f"  {voice_id}: {description}")
        print(f"\nLanguage codes:\n")
        for code, lang in LANGUAGE_CODES.items():
            print(f"  {code}: {lang}")
        return

    # Get text from argument or file
    if args.file:
        with open(args.file, 'r', encoding='utf-8') as f:
            text = f.read().strip()
    elif args.text:
        text = args.text
    else:
        parser.print_help()
        print("\nError: Please provide text or use --file to read from a file")
        sys.exit(1)

    if not text:
        print("Error: No text provided")
        sys.exit(1)

    generate_speech(
        text=text,
        voice=args.voice,
        lang_code=args.lang,
        output_dir=args.output,
    )


if __name__ == '__main__':
    main()
