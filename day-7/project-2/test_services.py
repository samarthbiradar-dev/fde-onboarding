"""Quick smoke test — run before agent.py to isolate which service fails."""
import os
from dotenv import load_dotenv
load_dotenv()

print("Testing imports...")
from livekit.plugins import elevenlabs, groq
print("  imports OK")

print("Testing ElevenLabs STT init...")
stt = elevenlabs.STT(api_key=os.environ["ELEVENLABS_API_KEY"])
print("  STT OK")

print("Testing Groq LLM init...")
llm = groq.LLM(model="llama-3.3-70b-versatile", api_key=os.environ["GROQ_API_KEY"])
print("  LLM OK")

print("Testing ElevenLabs TTS init...")
tts = elevenlabs.TTS(
    api_key=os.environ["ELEVENLABS_API_KEY"],
    voice_id=os.environ.get("ELEVENLABS_VOICE_ID", "pNInz6obpgDQGcFmaJgB"),
    model="eleven_turbo_v2_5",
)
print("  TTS OK")

print("\nAll services initialized. Run: venv/bin/python agent.py dev")
