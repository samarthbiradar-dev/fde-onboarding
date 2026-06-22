"""
Full Voice Pipeline — Capstone (with function calling)
Flow: Mic → ElevenLabs Scribe (STT) → Groq LLM + Tools → ElevenLabs TTS → Speaker

Tools available:
  get_current_time  — real time in any timezone
  get_weather       — live weather anywhere in the world
  calculate         — maths, percentages, compound interest
  convert_currency  — live exchange rates (USD→INR, EUR→GBP, etc.)
"""
import json
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

from tools import TOOLS, call_tool

load_dotenv()

eleven      = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

SAMPLE_RATE = 16000
DURATION    = 6
VOICE_ID    = "JBFqnCBsd6RMkjVDRZzb"   # George
TTS_MODEL   = "eleven_flash_v2_5"
LLM_MODEL   = "llama-3.3-70b-versatile"

SYSTEM = (
    "You are a smart voice assistant with live tools. "
    "Use tools whenever the question requires real-time data: time, weather, math, or currency. "
    "Keep answers short and conversational — you're being spoken aloud, not read on a screen. "
    "No markdown, no bullet points, no asterisks. Plain natural speech only."
)

history = [{"role": "system", "content": SYSTEM}]


def record(duration: int) -> str:
    print(f"  🎙  Recording {duration}s — speak now!")
    audio = sd.rec(int(duration * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1, dtype="int16")
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


def ask_with_tools(question: str) -> str:
    history.append({"role": "user", "content": question})

    # First call — model may request tool(s)
    response = groq_client.chat.completions.create(
        model=LLM_MODEL,
        messages=history,
        tools=TOOLS,
        tool_choice="auto",
    )
    msg = response.choices[0].message

    # No tool needed — direct answer
    if not msg.tool_calls:
        history.append({"role": "assistant", "content": msg.content})
        return msg.content

    # Execute every tool the model requested
    history.append(msg)
    for tc in msg.tool_calls:
        name   = tc.function.name
        args   = json.loads(tc.function.arguments)
        result = call_tool(name, args)
        print(f"  [tool] {name}({args}) → {result}")
        history.append({"role": "tool", "tool_call_id": tc.id, "content": result})

    # Second call — model answers using tool results
    final = groq_client.chat.completions.create(
        model=LLM_MODEL,
        messages=history,
        tools=TOOLS,
    )
    answer = final.choices[0].message.content
    history.append({"role": "assistant", "content": answer})
    return answer


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


def run_turn():
    input("\nPress Enter to speak  (Ctrl+C to quit)...")

    t0        = time.perf_counter()
    path      = record(DURATION)
    t_rec_end = time.perf_counter()

    print("  Transcribing...")
    question = transcribe(path)
    os.unlink(path)
    t_stt = time.perf_counter()

    if not question:
        print("  No speech detected — try again.")
        return

    print(f"  You: {question}")

    print("  Thinking...")
    answer = ask_with_tools(question)
    t_llm  = time.perf_counter()
    print(f"  Assistant: {answer}")

    print("  Speaking...")
    speak(answer)
    t_done = time.perf_counter()

    print(f"\n  ┌─ Latency ──────────────────────────")
    print(f"  │  STT            {t_stt  - t_rec_end:.2f}s")
    print(f"  │  LLM + tools    {t_llm  - t_stt:.2f}s")
    print(f"  │  TTS + playback {t_done - t_llm:.2f}s")
    print(f"  │  End-to-end     {t_done - t_rec_end:.2f}s")
    print(f"  └────────────────────────────────────")


def main():
    print("Voice Assistant with Live Tools")
    print("Tools: time · weather · calculator · currency")
    print("=" * 45)
    print("\nTry asking:")
    print("  • What time is it in Bangkok right now?")
    print("  • What's the weather in Tokyo?")
    print("  • What's 1000 dollars compounded at 8% for 5 years?")
    print("  • Convert 500 euros to Indian rupees")
    print("  • What time is it in New York, London, and Singapore?")
    print("  • What's 18 percent tip on a 63 dollar bill?")
    print("  • Is it raining in Mumbai right now?")
    print("  • If it's 3pm in Dubai, what time is it in Los Angeles?")
    print()
    while True:
        try:
            run_turn()
        except KeyboardInterrupt:
            print("\nBye!")
            break


if __name__ == "__main__":
    main()
