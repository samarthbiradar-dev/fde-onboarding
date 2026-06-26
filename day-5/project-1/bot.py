"""Pipecat basic local example.

Pipeline: Groq LLM → ElevenLabs TTS → local speakers

Run:
    python bot.py
"""

import asyncio
import os

from dotenv import load_dotenv

load_dotenv()

from pipecat.frames.frames import EndFrame, LLMContextFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.services.groq.llm import GroqLLMService
from pipecat.transports.local.audio import LocalAudioTransport, LocalAudioTransportParams
from pipecat.workers.runner import WorkerRunner


async def main():
    transport = LocalAudioTransport(
        LocalAudioTransportParams(audio_out_enabled=True)
    )

    llm = GroqLLMService(
        api_key=os.environ["GROQ_API_KEY"],
        model="llama-3.1-8b-instant",
    )

    tts = ElevenLabsTTSService(
        api_key=os.environ["ELEVENLABS_API_KEY"],
        voice_id=os.environ.get("ELEVENLABS_VOICE_ID", "pNInz6obpgDQGcFmaJgB"),
    )

    pipeline = Pipeline([llm, tts, transport.output()])

    worker = PipelineWorker(
        pipeline,
        idle_timeout_secs=15,
        cancel_runner_on_idle_timeout=True,
    )

    context = LLMContext(
        messages=[
            {
                "role": "system",
                "content": "You are a friendly voice assistant. Keep your response to one short sentence.",
            },
            {"role": "user", "content": "Say hello and tell me what you can do."},
        ]
    )

    runner = WorkerRunner()
    await runner.add_workers(worker)

    async def feed():
        await asyncio.sleep(0.5)
        await worker.queue_frame(LLMContextFrame(context))

    await asyncio.gather(runner.run(), feed())


if __name__ == "__main__":
    print("Starting Pipecat local bot (Groq LLM → ElevenLabs TTS → speakers)...")
    asyncio.run(main())
