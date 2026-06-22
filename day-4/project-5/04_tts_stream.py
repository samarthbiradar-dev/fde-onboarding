"""
TTS Part B — Streaming TTS: measures time-to-first-audio-chunk.
The API streams chunks as they're generated rather than waiting for
the full audio to be ready first.
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
    "Streaming text to speech means audio starts arriving almost immediately. "
    "The first chunk of audio comes back before the entire sentence has been processed, "
    "which dramatically reduces the time before you hear anything."
)

print(f"Streaming speech for:\n{TEXT}\n")
start             = time.perf_counter()
first_chunk_time  = None
chunks            = []

audio_stream = client.text_to_speech.convert_as_stream(
    text=TEXT,
    voice_id=VOICE_ID,
    model_id=MODEL,
    output_format="mp3_44100_128",
)

for chunk in audio_stream:
    if chunk:
        if first_chunk_time is None:
            first_chunk_time = time.perf_counter()
            print(f"First audio chunk: {first_chunk_time - start:.3f}s")
        chunks.append(chunk)

total_time = time.perf_counter() - start
print(f"All chunks received: {total_time:.2f}s")
print("Playing...")

with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
    f.write(b"".join(chunks))
    tmp_path = f.name

subprocess.run(["afplay", tmp_path], check=True)
os.unlink(tmp_path)
