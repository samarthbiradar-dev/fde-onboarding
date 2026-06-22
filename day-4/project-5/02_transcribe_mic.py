"""
STT Part B — Record from microphone, then transcribe with ElevenLabs Scribe.
Saves the recording as recording.wav so 01_transcribe_file.py can reuse it.
"""
import os
import time

import numpy as np
import sounddevice as sd
import soundfile as sf
from dotenv import load_dotenv
from elevenlabs.client import ElevenLabs

load_dotenv()

client      = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))
SAMPLE_RATE = 16000
DURATION    = 5
OUTPUT_FILE = "recording.wav"

print(f"Recording for {DURATION} seconds — speak now!")
audio = sd.rec(
    int(DURATION * SAMPLE_RATE),
    samplerate=SAMPLE_RATE,
    channels=1,
    dtype="int16",
)
sd.wait()
print("Recording done.\n")

sf.write(OUTPUT_FILE, audio, SAMPLE_RATE)

print("Transcribing...")
start = time.perf_counter()

with open(OUTPUT_FILE, "rb") as f:
    result = client.speech_to_text.convert(
        file=f,
        model_id="scribe_v1",
        language_code="en",
        tag_audio_events=False,
        diarize=False,
    )

elapsed = time.perf_counter() - start
print(f"You said: {result.text}")
print(f"Time taken: {elapsed:.2f}s")
print(f"Saved: {OUTPUT_FILE}")
