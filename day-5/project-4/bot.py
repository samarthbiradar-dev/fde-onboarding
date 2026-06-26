"""Day 5 Project 4 — Latency tracking + pro-grade optimizations.

What's new vs project-2/3:
  - Per-turn latency breakdown: STT / LLM TTFT / TTS TTFT / E2E
  - Rolling average over last 10 turns
  - Three in-pipeline probes capture timestamps at each stage boundary
  - Removed LLM completion-gate (project-3) — saves 300-600 ms per turn
  - Audio SmartTurn only (local neural ONNX, no network call)
  - Shorter system prompt (fewer prompt tokens → lower LLM TTFT)
  - SpeakerEchoMuteStrategy: mutes mic during AND 0.8 s after bot speech
    (AlwaysUserMuteStrategy only mutes DURING speech; echo audio captured
     during playback arrives as a TranscriptionFrame ~300 ms AFTER the bot
     stops speaking — the cooldown window catches that tail)

Latency breakdown printed per turn:
  STT      = UserStopped  → TranscriptionFrame    (speech recognition)
  LLM TTFT = Transcription → LLMFullResponseStart  (context build + first token)
  TTS TTFT = LLMStart     → TTSStarted             (sentence aggregation + synthesis start)
  Output   = TTSStarted   → first TTSAudioRawFrame  (first audio chunk to transport)
  E2E      = UserStopped  → first TTSAudioRawFrame  (total pipeline latency)

Run:
    python bot.py

Press Ctrl+C to quit.
"""

import asyncio
import os
import sys
import time
from collections import deque
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()

from loguru import logger

from pipecat.audio.turn.smart_turn.base_smart_turn import SmartTurnParams
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    EndFrame,
    InterruptionFrame,
    LLMFullResponseStartFrame,
    TTSAudioRawFrame,
    TTSSpeakFrame,
    TTSStartedFrame,
    TranscriptionFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.processors.audio.vad_processor import VADProcessor
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.services.groq.llm import GroqLLMService
from pipecat.services.groq.stt import GroqSTTService
from pipecat.transports.local.audio import LocalAudioTransport, LocalAudioTransportParams
from pipecat.turns.user_mute.base_user_mute_strategy import BaseUserMuteStrategy
from pipecat.turns.user_stop.turn_analyzer_user_turn_stop_strategy import (
    TurnAnalyzerUserTurnStopStrategy,
)
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from pipecat.workers.runner import WorkerRunner

logger.remove()
logger.add(sys.stderr, level="WARNING")  # only warnings+ to keep the latency output readable

# ─── Echo suppression ────────────────────────────────────────────────────────

class SpeakerEchoMuteStrategy(BaseUserMuteStrategy):
    """Mutes mic during bot speech PLUS a cooldown window after it stops.

    Why the cooldown: AlwaysUserMuteStrategy deactivates the moment
    BotStoppedSpeakingFrame fires. But the echo audio captured during
    playback reaches Groq STT ~300 ms later and arrives as a
    TranscriptionFrame after the mute has already lifted — causing the
    echo loop. The cooldown keeps the mute active long enough to catch
    that transcription.

    Default cooldown_secs=0.8 covers the typical 0.2 s VAD silence +
    0.3 s Groq STT latency with a comfortable margin.
    """

    def __init__(self, cooldown_secs: float = 0.8):
        super().__init__()
        self._cooldown_secs = cooldown_secs
        self._mute_until: float = 0.0

    async def process_frame(self, frame) -> bool:
        await super().process_frame(frame)
        if isinstance(frame, BotStartedSpeakingFrame):
            self._mute_until = float("inf")     # mute indefinitely until stopped
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self._mute_until = time.perf_counter() + self._cooldown_secs
        return time.perf_counter() < self._mute_until


# ─── Latency tracking ────────────────────────────────────────────────────────

HISTORY_SIZE = 10
DIVIDER = "─" * 56


@dataclass
class _TurnRecord:
    t0: float | None = None          # user stopped speaking
    t_stt: float | None = None       # transcription received
    t_llm: float | None = None       # LLM started streaming
    t_tts: float | None = None       # TTS started generating
    t_audio: float | None = None     # first audio chunk to transport
    text: str = ""
    reported: bool = False


class LatencyTracker:
    """Shared state across pipeline probes; prints breakdown after each turn."""

    def __init__(self):
        self._turn = _TurnRecord()
        self._history: deque[float] = deque(maxlen=HISTORY_SIZE)

    # ── called by probes ──────────────────────────────────────────────────

    def on_user_stopped(self):
        self._turn = _TurnRecord(t0=time.perf_counter())

    def on_transcription(self, text: str):
        if self._turn.t0 is not None and self._turn.t_stt is None:
            self._turn.t_stt = time.perf_counter()
            self._turn.text = text

    def on_llm_started(self):
        if self._turn.t_stt is not None and self._turn.t_llm is None:
            self._turn.t_llm = time.perf_counter()

    def on_tts_started(self):
        if self._turn.t_llm is not None and self._turn.t_tts is None:
            self._turn.t_tts = time.perf_counter()

    def on_first_audio(self):
        if self._turn.t_tts is not None and self._turn.t_audio is None:
            self._turn.t_audio = time.perf_counter()
            self._report()

    def on_interrupted(self):
        self._turn = _TurnRecord()

    # ── reporting ─────────────────────────────────────────────────────────

    def _report(self):
        r = self._turn
        if r.reported or r.t0 is None or r.t_audio is None:
            return
        r.reported = True

        def ms(a, b):
            if a is None or b is None:
                return None
            return (b - a) * 1000

        stt_ms  = ms(r.t0,    r.t_stt)
        llm_ms  = ms(r.t_stt, r.t_llm)
        tts_ms  = ms(r.t_llm, r.t_tts)
        out_ms  = ms(r.t_tts, r.t_audio)
        e2e_ms  = ms(r.t0,    r.t_audio)

        self._history.append(e2e_ms)
        avg = sum(self._history) / len(self._history)

        preview = (r.text[:42] + "…") if len(r.text) > 42 else r.text

        def fmt(v):
            return f"{v:>6.0f} ms" if v is not None else "  n/a   "

        print(f"\n{DIVIDER}")
        print(f'  "{preview}"')
        print(f"  STT         {fmt(stt_ms)}  (speech recognition)")
        print(f"  LLM TTFT    {fmt(llm_ms)}  (first token)")
        print(f"  TTS TTFT    {fmt(tts_ms)}  (sentence aggregation + synthesis)")
        print(f"  Output      {fmt(out_ms)}  (first audio chunk)")
        print(f"  {'─'*40}")
        print(
            f"  E2E         {fmt(e2e_ms)}"
            f"  (avg {len(self._history)}-turn: {avg:.0f} ms)"
        )
        print(f"{DIVIDER}\n", flush=True)


# ─── Pipeline probe ───────────────────────────────────────────────────────────

class LatencyProbe(FrameProcessor):
    """Thin pass-through processor that records timestamps for specific frames."""

    def __init__(self, tracker: LatencyTracker, probe_id: str):
        super().__init__(name=f"LatencyProbe-{probe_id}")
        self._tracker = tracker
        self._probe_id = probe_id

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)

        if direction == FrameDirection.DOWNSTREAM:
            if self._probe_id == "vad":
                if isinstance(frame, UserStoppedSpeakingFrame):
                    self._tracker.on_user_stopped()
                elif isinstance(frame, InterruptionFrame):
                    self._tracker.on_interrupted()

            elif self._probe_id == "stt":
                if isinstance(frame, TranscriptionFrame):
                    self._tracker.on_transcription(frame.text)

            elif self._probe_id == "post_tts":
                if isinstance(frame, LLMFullResponseStartFrame):
                    self._tracker.on_llm_started()
                elif isinstance(frame, TTSStartedFrame):
                    self._tracker.on_tts_started()
                elif isinstance(frame, TTSAudioRawFrame):
                    self._tracker.on_first_audio()

        await self.push_frame(frame, direction)


# ─── Main ─────────────────────────────────────────────────────────────────────

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

    # Concise system prompt: fewer prompt tokens → lower LLM latency.
    context = LLMContext(
        messages=[
            {
                "role": "system",
                "content": (
                    "Voice assistant. One or two plain sentences per reply. "
                    "No markdown or special characters."
                ),
            }
        ]
    )

    # VAD: stop_secs=0.2 is the value LocalSmartTurnAnalyzerV3 is calibrated for.
    vad = SileroVADAnalyzer(
        params=VADParams(
            confidence=0.85,
            min_volume=0.75,
            start_secs=0.4,
            stop_secs=0.2,
        )
    )

    # Audio SmartTurn only — no LLM gate (removes 300-600 ms vs project-3).
    smart_turn = TurnAnalyzerUserTurnStopStrategy(
        turn_analyzer=LocalSmartTurnAnalyzerV3(params=SmartTurnParams(stop_secs=3.0))
    )

    context_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            user_mute_strategies=[SpeakerEchoMuteStrategy(cooldown_secs=0.8)],
            user_turn_strategies=UserTurnStrategies(stop=[smart_turn]),
        ),
    )

    tracker = LatencyTracker()

    pipeline = Pipeline(
        [
            transport.input(),
            VADProcessor(vad_analyzer=vad),
            LatencyProbe(tracker, "vad"),       # t0: UserStoppedSpeakingFrame
            stt,
            LatencyProbe(tracker, "stt"),       # t_stt: TranscriptionFrame
            context_aggregator.user(),
            llm,
            tts,
            LatencyProbe(tracker, "post_tts"),  # t_llm: LLMFullResponseStartFrame
                                                # t_tts: TTSStartedFrame
                                                # t_audio: first TTSAudioRawFrame
            transport.output(),
            context_aggregator.assistant(),
        ]
    )

    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(enable_metrics=False),
        idle_timeout_secs=None,
    )
    runner = WorkerRunner()
    await runner.add_workers(worker)

    async def greet():
        await asyncio.sleep(1.0)
        await worker.queue_frame(
            TTSSpeakFrame("Ready. Latency breakdown will appear after each reply.")
        )

    print(f"\n{DIVIDER}")
    print("  Latency tracker active.")
    print("  Ask something and watch the breakdown below each reply.")
    print(f"{DIVIDER}\n", flush=True)

    try:
        await asyncio.gather(runner.run(), greet())
    except KeyboardInterrupt:
        print("\nStopping…", flush=True)
        await worker.queue_frame(EndFrame())


if __name__ == "__main__":
    asyncio.run(main())
