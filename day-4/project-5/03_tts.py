"""
TTS Part A — Convert text to speech with ElevenLabs and play it.
"""
import os
import subprocess
import tempfile
import time

from dotenv import load_dotenv
from elevenlabs.client import ElevenLabs

load_dotenv()

client   = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))
VOICE_ID = "JBFqnCBsd6RMkjVDRZzb"  # George
MODEL    = "eleven_flash_v2_5"
TEXT     = (
    "Hello! This is ElevenLabs text to speech. "
    "Plivo is a cloud communications platform that lets developers "
    "build voice and messaging applications using simple APIs."
)

print(f"Generating speech for:\n{TEXT}\n")
start = time.perf_counter()

audio = client.text_to_speech.convert(
    text=TEXT,
    voice_id=VOICE_ID,
    model_id=MODEL,
    output_format="mp3_44100_128",
)

with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
    for chunk in audio:
        if chunk:
            f.write(chunk)
    tmp_path = f.name

generated = time.perf_counter() - start
print(f"Generated in {generated:.2f}s — playing now...")

subprocess.run(["afplay", tmp_path], check=True)
os.unlink(tmp_path)
