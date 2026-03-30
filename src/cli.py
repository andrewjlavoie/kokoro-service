#!/usr/bin/env python3
"""
Kokoro TTS - Text-to-Speech Generator

A simple script to generate speech from text using the Kokoro-82M model.
"""

import argparse
import sys
from pathlib import Path

import soundfile as sf

from src.tts.constants import LANGUAGE_CODES, SAMPLE_RATE, VOICES as EXAMPLE_VOICES
from src.tts.engine import KokoroTTS


def generate_speech(
    text: str,
    voice: str = 'af_heart',
    lang_code: str = 'a',
    output_dir: str = 'output',
) -> list[Path]:
    """
    Generate speech from text using Kokoro TTS.

    Args:
        text: The text to convert to speech
        voice: Voice ID to use (e.g., 'af_heart', 'am_adam')
        lang_code: Language code ('a' for American English, etc.)
        output_dir: Directory to save output files

    Returns:
        List of paths to generated audio files
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    print(f"Initializing Kokoro pipeline (lang={lang_code})...")
    tts = KokoroTTS(voice=voice, lang_code=lang_code)

    print(f"Generating speech with voice '{voice}'...")
    output_files = []
    for i, segment in enumerate(tts.synthesize_stream(text)):
        output_file = output_path / f"output_{i:03d}.wav"
        sf.write(str(output_file), segment, SAMPLE_RATE)
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
