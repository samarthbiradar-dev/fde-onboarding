"""Verify that Groq and ElevenLabs API keys are working."""

import asyncio
import os

from dotenv import load_dotenv

load_dotenv()


async def check_groq():
    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        api_key=os.environ["GROQ_API_KEY"],
        base_url="https://api.groq.com/openai/v1",
    )
    resp = await client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": "Reply with just the word: OK"}],
        max_tokens=5,
    )
    print(f"  Groq LLM ✓  ({resp.choices[0].message.content.strip()})")


async def check_elevenlabs():
    from elevenlabs import ElevenLabs

    client = ElevenLabs(api_key=os.environ["ELEVENLABS_API_KEY"])
    voice_id = os.environ.get("ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb")
    audio = client.text_to_speech.convert(
        text="Test.",
        voice_id=voice_id,
        model_id="eleven_flash_v2_5",
        output_format="mp3_44100_128",
    )
    chunks = list(audio)
    print(f"  ElevenLabs TTS ✓  ({len(chunks)} audio chunks synthesized)")


async def main():
    print("\nChecking API keys...\n")
    errors = []

    for name, coro in [
        ("Groq", check_groq()),
        ("ElevenLabs", check_elevenlabs()),
    ]:
        try:
            await coro
        except KeyError as e:
            errors.append(f"  {name} ✗  missing env var: {e}")
        except Exception as e:
            errors.append(f"  {name} ✗  {e}")

    if errors:
        print("\nFailed:")
        for e in errors:
            print(e)
    else:
        print("\nAll keys valid — ready to run bot.py\n")


if __name__ == "__main__":
    asyncio.run(main())
