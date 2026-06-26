"""Day 5 Project 2 — Local voice bot with interruptions.

Pipeline: mic → Silero VAD → Groq STT (Whisper) → Groq LLM → ElevenLabs TTS → speakers

Interruption handling: if you speak while the bot is talking it immediately
stops and processes your new input.

Run:
    python bot.py

Press Ctrl+C to quit.
"""

import asyncio
import os
import sys

from dotenv import load_dotenv

load_dotenv()

from loguru import logger

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import EndFrame, TTSSpeakFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.turns.user_mute.always_user_mute_strategy import AlwaysUserMuteStrategy
from pipecat.processors.audio.vad_processor import VADProcessor
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.services.groq.llm import GroqLLMService
from pipecat.services.groq.stt import GroqSTTService
from pipecat.transports.local.audio import LocalAudioTransport, LocalAudioTransportParams
from pipecat.workers.runner import WorkerRunner

# Keep logs tidy — only show INFO and above
logger.remove()
logger.add(sys.stderr, level="INFO")


async def main():
    transport = LocalAudioTransport(
        LocalAudioTransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
        )
    )

    stt = GroqSTTService(
        api_key=os.environ["GROQ_API_KEY"],
        settings=GroqSTTService.Settings(model="whisper-large-v3-turbo"),
    )

    llm = GroqLLMService(
        api_key=os.environ["GROQ_API_KEY"],
        settings=GroqLLMService.Settings(model="llama-3.1-8b-instant"),
    )

    tts = ElevenLabsTTSService(
        api_key=os.environ["ELEVENLABS_API_KEY"],
        settings=ElevenLabsTTSService.Settings(
            voice=os.environ.get("ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb"),
            model="eleven_flash_v2_5",
        ),
    )

    context = LLMContext(
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a helpful voice assistant. "
                    "Keep every response short — two sentences at most. "
                    "Do not use markdown, bullet points, or special characters."
                ),
            }
        ]
    )

    # Tighter VAD — higher confidence + volume filters background noise.
    # stop_secs=0.2 matches the TurnAnalyzer's built-in calibration.
    vad = SileroVADAnalyzer(
        params=VADParams(
            confidence=0.85,
            min_volume=0.75,
            start_secs=0.4,
            stop_secs=0.2,
        )
    )

    # AlwaysUserMuteStrategy: mic input is suppressed while the bot is
    # speaking. This prevents the TTS audio from being fed back into the
    # STT pipeline (speaker→mic echo on MacBook internal hardware).
    # If you use headphones you can remove this and get full mid-sentence
    # interruption support.
    context_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            user_mute_strategies=[AlwaysUserMuteStrategy()]
        ),
    )

    pipeline = Pipeline(
        [
            transport.input(),
            VADProcessor(vad_analyzer=vad),
            stt,
            context_aggregator.user(),
            llm,
            tts,
            transport.output(),
            context_aggregator.assistant(),
        ]
    )

    # idle_timeout_secs=None disables auto-shutdown so the bot waits indefinitely.
    worker = PipelineWorker(
        pipeline,
        idle_timeout_secs=None,
    )

    runner = WorkerRunner()
    await runner.add_workers(worker)

    # Speak a greeting so the user knows the bot is ready.
    async def greet():
        await asyncio.sleep(1.0)
        await worker.queue_frame(TTSSpeakFrame("Hey, I'm ready. Go ahead and ask me anything."))

    print("\n--- Bot starting. You will hear a greeting when it is ready. ---\n", flush=True)

    try:
        await asyncio.gather(runner.run(), greet())
    except KeyboardInterrupt:
        print("\nStopping…", flush=True)
        await worker.queue_frame(EndFrame())


if __name__ == "__main__":
    asyncio.run(main())
