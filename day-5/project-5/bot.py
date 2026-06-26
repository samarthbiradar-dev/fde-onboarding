"""Day 5 Project 5 — Function calling in a real conversational voice bot.

"Jarvis" is a general-purpose voice assistant you can ask anything. It holds
context across turns, asks clarifying questions when a request is vague, and
calls tools only when relevant.

Model stack:
  STT  ElevenLabs Scribe (streaming)
  LLM  Groq llama-3.3-70b-versatile
  TTS  ElevenLabs (WebSocket, eleven_turbo_v2_5)

Two tools:
  get_current_time()               → real wall-clock time (system local tz)
  get_weather(location: str)       → mock weather data

Run:
    python bot.py

Press Ctrl+C to quit.
"""

import asyncio
import os
import sys
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime

import aiohttp
from dotenv import load_dotenv

load_dotenv()

from loguru import logger

from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.audio.turn.smart_turn.base_smart_turn import SmartTurnParams
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    EndFrame,
    ErrorFrame,
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
from pipecat.services.elevenlabs.stt import ElevenLabsSTTService
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.services.groq.llm import GroqLLMService
from pipecat.services.llm_service import FunctionCallParams
from pipecat.transports.local.audio import LocalAudioTransport, LocalAudioTransportParams
from pipecat.turns.user_mute.base_user_mute_strategy import BaseUserMuteStrategy
from pipecat.turns.user_mute.function_call_user_mute_strategy import FunctionCallUserMuteStrategy
from pipecat.turns.user_stop.turn_analyzer_user_turn_stop_strategy import (
    TurnAnalyzerUserTurnStopStrategy,
)
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from pipecat.workers.runner import WorkerRunner

logger.remove()
logger.add(sys.stderr, level="WARNING")

# ─── Echo suppression ────────────────────────────────────────────────────────

class SpeakerEchoMuteStrategy(BaseUserMuteStrategy):
    """Mutes mic during bot speech + a short cooldown window after it stops."""

    def __init__(self, cooldown_secs: float = 0.8):
        super().__init__()
        self._cooldown_secs = cooldown_secs
        self._mute_until: float = 0.0

    async def process_frame(self, frame) -> bool:
        await super().process_frame(frame)
        if isinstance(frame, BotStartedSpeakingFrame):
            self._mute_until = float("inf")
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self._mute_until = time.perf_counter() + self._cooldown_secs
        return time.perf_counter() < self._mute_until


# ─── Tool handlers ────────────────────────────────────────────────────────────

async def handle_get_current_time(params: FunctionCallParams) -> None:
    now = datetime.now().astimezone()
    tz_name = now.tzname() or ""
    result = now.strftime("%-I:%M %p") + (f" {tz_name}" if tz_name else "") + now.strftime(", %A %B %-d")
    print(f"  [tool] get_current_time → {result}", flush=True)
    await params.result_callback(result)


async def handle_get_weather(params: FunctionCallParams) -> None:
    location = params.arguments.get("location", "unknown location")
    _MOCK = {
        "new york": ("72°F", "partly cloudy", "55%"),
        "nyc":      ("72°F", "partly cloudy", "55%"),
        "london":   ("61°F", "overcast",       "80%"),
        "tokyo":    ("79°F", "sunny",           "40%"),
        "mumbai":   ("88°F", "humid and hazy",  "70%"),
        "paris":    ("65°F", "light rain",      "75%"),
        "sydney":   ("68°F", "clear skies",     "30%"),
        "dubai":    ("104°F", "sunny and dry",  "10%"),
    }
    key = location.lower().strip()
    temp, cond, humidity = _MOCK.get(key, ("75°F", "mostly clear", "45%"))
    result = f"{location}: {temp}, {cond}, humidity {humidity}"
    print(f"  [tool] get_weather({location!r}) → {result}", flush=True)
    await params.result_callback(result)


# ─── Tool schemas ─────────────────────────────────────────────────────────────

get_current_time_schema = FunctionSchema(
    name="get_current_time",
    description="Get the current local time and date. Call this when the user asks what time it is or what day it is.",
    properties={},
    required=[],
    handler=handle_get_current_time,
)

get_weather_schema = FunctionSchema(
    name="get_weather",
    description="Get the current weather for a city or location. Call this when the user asks about the weather.",
    properties={
        "location": {
            "type": "string",
            "description": "The city or location to get weather for, e.g. 'New York' or 'London'.",
        }
    },
    required=["location"],
    handler=handle_get_weather,
)


# ─── Latency tracking ────────────────────────────────────────────────────────

HISTORY_SIZE = 10
DIVIDER = "─" * 56


@dataclass
class _TurnRecord:
    t0: float | None = None
    t_stt: float | None = None
    t_llm: float | None = None
    t_tts: float | None = None
    t_audio: float | None = None
    text: str = ""
    reported: bool = False


class LatencyTracker:
    def __init__(self):
        self._turn = _TurnRecord()
        self._history: deque[float] = deque(maxlen=HISTORY_SIZE)

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

    def _report(self):
        r = self._turn
        if r.reported or r.t0 is None or r.t_audio is None:
            return
        r.reported = True

        def ms(a, b):
            return (b - a) * 1000 if (a is not None and b is not None) else None

        stt_ms = ms(r.t0,    r.t_stt)
        llm_ms = ms(r.t_stt, r.t_llm)
        tts_ms = ms(r.t_llm, r.t_tts)
        out_ms = ms(r.t_tts, r.t_audio)
        e2e_ms = ms(r.t0,    r.t_audio)

        self._history.append(e2e_ms)
        avg = sum(self._history) / len(self._history)
        preview = (r.text[:42] + "…") if len(r.text) > 42 else r.text

        def fmt(v):
            return f"{v:>6.0f} ms" if v is not None else "  n/a   "

        print(f"\n{DIVIDER}")
        print(f'  "{preview}"')
        print(f"  STT         {fmt(stt_ms)}  (speech recognition)")
        print(f"  LLM TTFT    {fmt(llm_ms)}  (first token / tool call)")
        print(f"  TTS TTFT    {fmt(tts_ms)}  (sentence agg + synthesis)")
        print(f"  Output      {fmt(out_ms)}  (first audio chunk)")
        print(f"  {'─'*40}")
        print(f"  E2E         {fmt(e2e_ms)}  (avg {len(self._history)}-turn: {avg:.0f} ms)")
        print(f"{DIVIDER}\n", flush=True)


class LatencyProbe(FrameProcessor):
    def __init__(self, tracker: LatencyTracker, probe_id: str, on_error=None):
        super().__init__(name=f"LatencyProbe-{probe_id}")
        self._tracker = tracker
        self._probe_id = probe_id
        self._on_error = on_error

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)

        if isinstance(frame, ErrorFrame) and self._on_error is not None:
            await self._on_error(frame.error)

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
    async with aiohttp.ClientSession() as session:
        transport = LocalAudioTransport(
            LocalAudioTransportParams(
                audio_in_enabled=True,
                audio_out_enabled=True,
            )
        )

        stt = ElevenLabsSTTService(
            api_key=os.environ["ELEVENLABS_API_KEY"],
            aiohttp_session=session,
        )

        llm = GroqLLMService(
            api_key=os.environ["GROQ_API_KEY"],
            settings=GroqLLMService.Settings(model="llama-3.3-70b-versatile"),
        )

        # Adam voice — composed, authoritative, suits Jarvis.
        # Override with ELEVENLABS_VOICE_ID env var if you want a different voice.
        tts = ElevenLabsTTSService(
            api_key=os.environ["ELEVENLABS_API_KEY"],
            settings=ElevenLabsTTSService.Settings(
                voice=os.environ.get("ELEVENLABS_VOICE_ID", "pNInz6obpgDQGcFmaJgB"),
                model="eleven_turbo_v2_5",
            ),
        )

        context = LLMContext(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are Jarvis, a sharp, composed, and genuinely helpful voice "
                        "assistant having a real spoken conversation. Think calm confidence with "
                        "a touch of dry wit — never robotic, never over-the-top. The person can "
                        "ask you about anything — general knowledge, advice, explanations, ideas, "
                        "casual chat — and you engage naturally, like a brilliant right-hand who "
                        "always has their back.\n\n"
                        "How you speak:\n"
                        "- This is VOICE, so sound natural. Use contractions and a relaxed tone. "
                        "Never use markdown, bullet points, asterisks, emoji, or symbols — they "
                        "get read aloud and sound terrible.\n"
                        "- Be concise by default: usually one to three sentences. Give a short "
                        "answer first, then offer to go deeper rather than dumping everything.\n"
                        "- When a request is vague or could go several ways, ASK a brief "
                        "clarifying question instead of guessing.\n"
                        "- Be proactive: after answering, it's good to ask a relevant follow-up "
                        "or suggest a next step when it genuinely helps.\n"
                        "- Remember what was said earlier in this conversation and refer back to it.\n\n"
                        "Your tools:\n"
                        "- get_current_time: call whenever the user asks the time or date.\n"
                        "- get_weather: call whenever the user asks about weather (this returns "
                        "sample data, so if it matters, mention it's approximate).\n"
                        "For everything else, just answer from what you know.\n\n"
                        "Be honest: you don't have live internet, so for fast-changing facts "
                        "(today's news, live prices, scores) say you can't check that live. "
                        "If you don't know something, say so briefly rather than making it up."
                    ),
                }
            ],
            tools=[get_current_time_schema, get_weather_schema],
        )

        vad = SileroVADAnalyzer(
            params=VADParams(
                confidence=0.85,
                min_volume=0.75,
                start_secs=0.4,
                stop_secs=0.2,
            )
        )

        smart_turn = TurnAnalyzerUserTurnStopStrategy(
            turn_analyzer=LocalSmartTurnAnalyzerV3(params=SmartTurnParams(stop_secs=3.0))
        )

        context_aggregator = LLMContextAggregatorPair(
            context,
            user_params=LLMUserAggregatorParams(
                user_mute_strategies=[
                    SpeakerEchoMuteStrategy(cooldown_secs=0.8),
                    FunctionCallUserMuteStrategy(),
                ],
                user_turn_strategies=UserTurnStrategies(stop=[smart_turn]),
            ),
        )

        tracker = LatencyTracker()
        _last_apology = [0.0]

        async def on_error(error: str):
            e = error.lower()
            if "429" in error or "rate_limit" in e:
                label = "rate limit hit — pause a few seconds"
            elif "quota" in e or "credit" in e:
                label = "API quota/credits exhausted"
            elif "failed to call a function" in e or "tool_use_failed" in e:
                label = "LLM invalid tool call (intermittent)"
            else:
                label = "service error"
            print(f"\n  [!] {label} — turn dropped.\n      {error[:160]}\n", flush=True)
            now = time.perf_counter()
            if now - _last_apology[0] > 6.0:
                _last_apology[0] = now
                await worker.queue_frame(
                    TTSSpeakFrame("Sorry, I didn't catch that. Could you say it again?")
                )

        pipeline = Pipeline(
            [
                transport.input(),
                VADProcessor(vad_analyzer=vad),
                LatencyProbe(tracker, "vad"),
                stt,
                LatencyProbe(tracker, "stt", on_error=on_error),
                context_aggregator.user(),
                llm,
                tts,
                LatencyProbe(tracker, "post_tts"),
                transport.output(),
                context_aggregator.assistant(),
            ]
        )

        worker = PipelineWorker(
            pipeline,
            params=PipelineParams(enable_metrics=False, audio_out_sample_rate=24000),
            idle_timeout_secs=None,
        )
        runner = WorkerRunner()
        await runner.add_workers(worker)

        async def greet():
            await asyncio.sleep(1.5)
            await worker.queue_frame(
                TTSSpeakFrame(
                    "All systems online. Jarvis here, at your service. "
                    "Ask me anything, and let's get to work. What do you need?"
                )
            )

        print(f"\n{DIVIDER}")
        print("  Jarvis — ElevenLabs STT + Groq LLM + ElevenLabs TTS")
        print("  Ask anything. Tools: get_current_time | get_weather(location)")
        print("  [tool] lines show when a function is called.")
        print(f"{DIVIDER}\n", flush=True)

        try:
            await asyncio.gather(runner.run(), greet())
        except KeyboardInterrupt:
            print("\nStopping…", flush=True)
            await worker.queue_frame(EndFrame())


if __name__ == "__main__":
    asyncio.run(main())
