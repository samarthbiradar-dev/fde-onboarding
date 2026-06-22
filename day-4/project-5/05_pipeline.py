"""
Full Voice Pipeline — Capstone
Flow: Mic → ElevenLabs Scribe (STT) → Groq LLM → ElevenLabs TTS → Speaker
Measures and prints latency at each stage and end-to-end.
"""
import os
import subprocess
import tempfile
import time

import numpy as np
import sounddevice as sd
import soundfile as sf
from dotenv import load_dotenv
from elevenlabs.client import ElevenLabs
from groq import Groq

load_dotenv()

eleven      = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

SAMPLE_RATE = 16000
DURATION    = 5
VOICE_ID    = "JBFqnCBsd6RMkjVDRZzb"  # George
TTS_MODEL   = "eleven_flash_v2_5"
LLM_MODEL   = "llama-3.3-70b-versatile"


def record(duration: int) -> str:
    print(f"  Recording {duration}s — speak now!")
    audio = sd.rec(
        int(duration * SAMPLE_RATE),
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="int16",
    )
    sd.wait()
    path = tempfile.mktemp(suffix=".wav")
    sf.write(path, audio, SAMPLE_RATE)
    return path


def transcribe(path: str) -> str:
    with open(path, "rb") as f:
        result = eleven.speech_to_text.convert(
            file=f,
            model_id="scribe_v1",
            language_code="en",
            tag_audio_events=False,
            diarize=False,
        )
    return result.text.strip()


def ask(question: str) -> str:
    response = groq_client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {
                "role":    "system",
                "content": "Answer helpfully and concisely in 2-3 sentences.",
            },
            {"role": "user", "content": question},
        ],
    )
    return response.choices[0].message.content


def speak(text: str):
    audio = eleven.text_to_speech.convert(
        text=text,
        voice_id=VOICE_ID,
        model_id=TTS_MODEL,
        output_format="mp3_44100_128",
    )
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        for chunk in audio:
            if chunk:
                f.write(chunk)
        tmp_path = f.name
    subprocess.run(["afplay", tmp_path], check=True)
    os.unlink(tmp_path)


def run_pipeline():
    print("\nPress Enter to ask a question (Ctrl+C to quit)...")
    input()

    # ── Step 1: Record ────────────────────────────────────────────────────────
    t0    = time.perf_counter()
    path  = record(DURATION)
    t_rec = time.perf_counter()

    # ── Step 2: STT ───────────────────────────────────────────────────────────
    print("  Transcribing...")
    question = transcribe(path)
    os.unlink(path)
    t_stt = time.perf_counter()

    if not question:
        print("  No speech detected — try again.\n")
        return

    print(f"  You said: {question}")

    # ── Step 3: LLM ───────────────────────────────────────────────────────────
    print("  Thinking...")
    answer = ask(question)
    t_llm = time.perf_counter()
    print(f"  Answer:   {answer}")

    # ── Step 4: TTS + play ────────────────────────────────────────────────────
    print("  Speaking...")
    speak(answer)
    t_tts = time.perf_counter()

    # ── Latency breakdown ─────────────────────────────────────────────────────
    print(f"\n  --- Latency ---")
    print(f"  STT (transcription): {t_stt - t_rec:.2f}s")
    print(f"  LLM (answer):        {t_llm - t_stt:.2f}s")
    print(f"  TTS (speech gen):    {t_tts - t_llm:.2f}s")
    print(f"  End-to-end:          {t_tts - t_rec:.2f}s  (from end of recording to end of playback)")


def main():
    print("Voice Pipeline: Mic → ElevenLabs STT → Groq LLM → ElevenLabs TTS")
    print("=" * 60)
    while True:
        try:
            run_pipeline()
        except KeyboardInterrupt:
            print("\nBye!")
            break


if __name__ == "__main__":
    main()
