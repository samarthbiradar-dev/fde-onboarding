"""Check whether the Day 5 API keys are currently usable.

This script intentionally prints only provider status, never key values.
"""

import asyncio
import os
import tempfile
import wave

from dotenv import load_dotenv


load_dotenv("project-5/.env")


def get_required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise KeyError(name)
    return value


def classify_error(exc: Exception) -> tuple[str, str]:
    text = str(exc)
    low = text.lower()
    if "quota" in low or "credits" in low or "insufficient_quota" in low:
        return "LIMIT/QUOTA", text
    if "rate" in low or "429" in low:
        return "RATE LIMITED", text
    if "401" in low or "unauthorized" in low or "invalid api key" in low:
        return "AUTH ERROR", text
    return "ERROR", text


async def check_groq_chat() -> None:
    from groq import AsyncGroq

    client = AsyncGroq(api_key=get_required_env("GROQ_API_KEY"))
    await client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": "Reply OK"}],
        max_tokens=2,
    )


async def check_groq_stt() -> None:
    from groq import AsyncGroq

    client = AsyncGroq(api_key=get_required_env("GROQ_API_KEY"))
    with tempfile.NamedTemporaryFile(suffix=".wav") as f:
        with wave.open(f.name, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(bytes(3200))

        with open(f.name, "rb") as audio:
            await client.audio.transcriptions.create(
                file=("silence.wav", audio.read()),
                model="whisper-large-v3-turbo",
            )


async def check_groq_tts() -> None:
    from groq import AsyncGroq

    client = AsyncGroq(api_key=get_required_env("GROQ_API_KEY"))
    response = await client.audio.speech.create(
        model="canopylabs/orpheus-v1-english",
        voice="autumn",
        input="Test.",
        response_format="wav",
    )
    data = await response.read()
    if not data:
        raise RuntimeError("empty TTS response")


async def check_gemini() -> None:
    from google import genai

    client = genai.Client(api_key=get_required_env("GEMINI_API_KEY"))
    client.models.generate_content(
        model="gemini-2.5-flash",
        contents="Reply with OK only.",
    )


async def check_elevenlabs() -> None:
    from elevenlabs import ElevenLabs

    client = ElevenLabs(api_key=get_required_env("ELEVENLABS_API_KEY"))
    voice_id = os.environ.get("ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb")
    chunks = list(
        client.text_to_speech.convert(
            text="Test.",
            voice_id=voice_id,
            model_id="eleven_flash_v2_5",
            output_format="mp3_44100_128",
        )
    )
    if not chunks:
        raise RuntimeError("empty ElevenLabs response")


async def check_assemblyai() -> None:
    import httpx

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(
            "https://api.assemblyai.com/v2/account",
            headers={"authorization": get_required_env("ASSEMBLYAI_API_KEY")},
        )
        if response.status_code >= 400:
            raise RuntimeError(
                f"status_code={response.status_code}, body={response.text[:300]}"
            )


async def main() -> None:
    checks = [
        ("Groq chat/LLM", check_groq_chat),
        ("Groq STT/Whisper", check_groq_stt),
        ("Groq TTS/Orpheus", check_groq_tts),
        ("Gemini LLM", check_gemini),
        ("ElevenLabs TTS", check_elevenlabs),
        ("AssemblyAI account", check_assemblyai),
    ]

    for name, check in checks:
        try:
            await check()
            print(f"{name}: OK")
        except KeyError as exc:
            print(f"{name}: MISSING ENV {exc}")
        except Exception as exc:
            kind, detail = classify_error(exc)
            detail = detail.replace("\n", " ")[:500]
            print(f"{name}: {kind}: {detail}")


if __name__ == "__main__":
    asyncio.run(main())
