"""
STT Part A — Transcribe an audio file using ElevenLabs Scribe.
Usage: python3 01_transcribe_file.py [audio_file]
       Defaults to recording.wav (run 02_transcribe_mic.py first to create it).
"""
import os
import sys
import time

from dotenv import load_dotenv
from elevenlabs.client import ElevenLabs

load_dotenv()

client     = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))
audio_file = sys.argv[1] if len(sys.argv) > 1 else "recording.wav"

if not os.path.exists(audio_file):
    print(f"File not found: {audio_file}")
    print("Run 02_transcribe_mic.py first to record something, or pass a file path.")
    sys.exit(1)

print(f"Transcribing: {audio_file}")
start = time.perf_counter()

with open(audio_file, "rb") as f:
    result = client.speech_to_text.convert(
        file=f,
        model_id="scribe_v1",
        language_code="en",
        tag_audio_events=False,
        diarize=False,
    )

elapsed = time.perf_counter() - start
print(f"\nTranscript: {result.text}")
print(f"Time taken: {elapsed:.2f}s")
