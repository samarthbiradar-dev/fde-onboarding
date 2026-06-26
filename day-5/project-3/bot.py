"""Day 5 Project 3 — SmartTurn: wait for a complete thought before replying.

What's new vs project-2:
  FilterIncompleteUserTurnStrategies adds a second, LLM-based gate on top of
  the audio SmartTurn neural model. After the audio model decides you have
  stopped speaking, the LLM reads your transcript and marks it:
    ✓  complete    → bot replies immediately
    ○  incomplete (short pause) → bot waits up to 6 s for you to continue
    ◐  incomplete (long pause)  → bot waits up to 12 s for you to continue

  This means the bot won't jump in after "I was thinking about..." because the
  LLM can tell the sentence is unfinished, even if there was a half-second gap.

Pipeline: mic → Silero VAD → Groq STT → [SmartTurn + LLM gate] → Groq LLM → ElevenLabs TTS → speakers

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

from pipecat.audio.turn.smart_turn.base_smart_turn import SmartTurnParams
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
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
from pipecat.processors.audio.vad_processor import VADProcessor
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.services.groq.llm import GroqLLMService
from pipecat.services.groq.stt import GroqSTTService
from pipecat.transports.local.audio import LocalAudioTransport, LocalAudioTransportParams
from pipecat.turns.user_mute.always_user_mute_strategy import AlwaysUserMuteStrategy
from pipecat.turns.user_stop.turn_analyzer_user_turn_stop_strategy import (
    TurnAnalyzerUserTurnStopStrategy,
)
from pipecat.turns.user_turn_completion_mixin import UserTurnCompletionConfig
from pipecat.turns.user_turn_strategies import FilterIncompleteUserTurnStrategies
from pipecat.workers.runner import WorkerRunner

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

    # Silero VAD: stop_secs=0.2 is the value SmartTurn is calibrated for.
    # The neural model uses its own 3-second silence fallback on top of this.
    vad = SileroVADAnalyzer(
        params=VADParams(
            confidence=0.85,
            min_volume=0.75,
            start_secs=0.4,
            stop_secs=0.2,
        )
    )

    # SmartTurn audio model — explicitly constructed so we can set stop_secs.
    # stop_secs=3 (the default): if the neural model hasn't decided after
    # 3 seconds of silence it forcibly ends the turn as a safety valve.
    smart_turn = LocalSmartTurnAnalyzerV3(
        params=SmartTurnParams(stop_secs=3.0)
    )

    # FilterIncompleteUserTurnStrategies:
    #   Layer 1 — audio SmartTurn (deferred): fires inference-triggered only
    #   Layer 2 — LLM gate: reads transcript, marks ✓/○/◐, finalizes or waits
    #
    # incomplete_short_timeout: seconds to wait after ○ (user trailed off)
    # incomplete_long_timeout:  seconds to wait after ◐ (user mid-sentence)
    smart_turn_strategy = TurnAnalyzerUserTurnStopStrategy(turn_analyzer=smart_turn)

    turn_strategies = FilterIncompleteUserTurnStrategies(
        stop=[smart_turn_strategy],
        config=UserTurnCompletionConfig(
            incomplete_short_timeout=6.0,
            incomplete_long_timeout=12.0,
        ),
    )

    context_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            user_mute_strategies=[AlwaysUserMuteStrategy()],
            user_turn_strategies=turn_strategies,
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

    worker = PipelineWorker(pipeline, idle_timeout_secs=None)
    runner = WorkerRunner()
    await runner.add_workers(worker)

    async def greet():
        await asyncio.sleep(1.0)
        await worker.queue_frame(
            TTSSpeakFrame(
                "Hey, I'm listening. I'll wait until you finish your thought before I reply."
            )
        )

    print("\n--- Bot starting. SmartTurn + LLM gate active. ---\n", flush=True)

    try:
        await asyncio.gather(runner.run(), greet())
    except KeyboardInterrupt:
        print("\nStopping…", flush=True)
        await worker.queue_frame(EndFrame())


if __name__ == "__main__":
    asyncio.run(main())
