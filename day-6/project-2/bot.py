"""Day 6 Project 2 — Pipecat voice bot over a Plivo phone call.

Replaces LocalAudioTransport with FastAPIWebsocketTransport + PlivoFrameSerializer
so the full Day-5 pipeline (ElevenLabs STT → Groq LLM → ElevenLabs TTS) runs
over a real phone call.

Audio flow:
  Caller mic → Plivo 8kHz μ-law → WebSocket → PlivoFrameSerializer (→ 16kHz PCM)
              → ElevenLabs STT → Groq LLM → ElevenLabs TTS (24kHz PCM)
              → PlivoFrameSerializer (→ 8kHz μ-law) → WebSocket → Plivo → caller ear

Run:
    uvicorn bot:app --host 0.0.0.0 --port 8000

Expose publicly:
    cloudflared tunnel --url http://localhost:8000

Set Plivo Answer URL to:
    https://<tunnel>/answer   (POST)

.env keys needed:
    ELEVENLABS_API_KEY
    GROQ_API_KEY
    SERVER_URL=https://<tunnel>
    PLIVO_AUTH_ID=<optional — enables auto hang-up when call ends>
    PLIVO_AUTH_TOKEN=<optional>
"""

import asyncio
import json
import os
import time

import aiohttp
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import PlainTextResponse
from loguru import logger

load_dotenv()

import sys
logger.remove()
logger.add(sys.stderr, level="WARNING")

from pipecat.audio.turn.smart_turn.base_smart_turn import SmartTurnParams
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    EndFrame,
    TTSSpeakFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.processors.audio.vad_processor import VADProcessor
from pipecat.serializers.plivo import PlivoFrameSerializer
from pipecat.services.elevenlabs.stt import ElevenLabsSTTService
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.services.groq.llm import GroqLLMService
from pipecat.services.llm_service import FunctionCallParams
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)
from pipecat.turns.user_mute.base_user_mute_strategy import BaseUserMuteStrategy
from pipecat.turns.user_mute.function_call_user_mute_strategy import FunctionCallUserMuteStrategy
from pipecat.turns.user_stop.turn_analyzer_user_turn_stop_strategy import (
    TurnAnalyzerUserTurnStopStrategy,
)
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from pipecat.workers.runner import WorkerRunner
from datetime import datetime

app = FastAPI()

SERVER_URL = os.environ.get("SERVER_URL", "").rstrip("/")


# ─── Echo suppression ────────────────────────────────────────────────────────

class SpeakerEchoMuteStrategy(BaseUserMuteStrategy):
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
    result = (
        now.strftime("%-I:%M %p")
        + (f" {tz_name}" if tz_name else "")
        + now.strftime(", %A %B %-d")
    )
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


get_current_time_schema = FunctionSchema(
    name="get_current_time",
    description="Get the current local time and date.",
    properties={},
    required=[],
    handler=handle_get_current_time,
)

get_weather_schema = FunctionSchema(
    name="get_weather",
    description="Get the current weather for a city or location.",
    properties={
        "location": {"type": "string", "description": "The city or location name."}
    },
    required=["location"],
    handler=handle_get_weather,
)


# ─── /answer ─────────────────────────────────────────────────────────────────

@app.post("/answer")
async def answer(request: Request):
    if not SERVER_URL:
        return PlainTextResponse("SERVER_URL not set in .env", status_code=500)

    form = dict(await request.form())
    print(f"\n[answer] call params: {form}", flush=True)

    ws_url = SERVER_URL.replace("https://", "wss://").replace("http://", "ws://")
    ws_url = f"{ws_url}/stream"

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Stream keepCallAlive="true" contentType="audio/x-mulaw;rate=8000" bidirectional="true">{ws_url}</Stream>
    <Wait length="3600"/>
</Response>"""

    print(f"[answer] streaming bidirectional to {ws_url}", flush=True)
    return PlainTextResponse(xml, media_type="text/xml")


# ─── /stream — full Pipecat pipeline over Plivo WebSocket ────────────────────

@app.websocket("/stream")
async def stream_endpoint(websocket: WebSocket):
    await websocket.accept()
    print("\n[stream] WebSocket connected", flush=True)

    # Read Plivo's start event to capture streamId and callId
    stream_id = "unknown"
    call_id = None
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=10.0)
        data = json.loads(raw)
        if data.get("event") == "start":
            start = data.get("start", {})
            stream_id = start.get("streamId", "unknown")
            call_id = start.get("callId")
            print(f"[stream] START streamId={stream_id} callId={call_id}", flush=True)
    except asyncio.TimeoutError:
        print("[stream] WARNING: no start event received within 10s", flush=True)
    except Exception as e:
        print(f"[stream] WARNING reading start event: {e}", flush=True)

    auth_id = os.environ.get("PLIVO_AUTH_ID")
    auth_token = os.environ.get("PLIVO_AUTH_TOKEN")
    auto_hang_up = bool(call_id and auth_id and auth_token)

    serializer = PlivoFrameSerializer(
        stream_id=stream_id,
        call_id=call_id if auto_hang_up else None,
        auth_id=auth_id if auto_hang_up else None,
        auth_token=auth_token if auto_hang_up else None,
        params=PlivoFrameSerializer.InputParams(auto_hang_up=auto_hang_up),
    )

    transport = FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            audio_in_sample_rate=16000,
            audio_out_sample_rate=24000,
            add_wav_header=False,
            serializer=serializer,
        ),
    )

    async with aiohttp.ClientSession() as session:
        stt = ElevenLabsSTTService(
            api_key=os.environ["ELEVENLABS_API_KEY"],
            aiohttp_session=session,
        )

        llm = GroqLLMService(
            api_key=os.environ["GROQ_API_KEY"],
            settings=GroqLLMService.Settings(model="llama-3.3-70b-versatile"),
        )

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
                        "assistant on a phone call. Think calm confidence with a touch of dry wit. "
                        "The person can ask you about anything — keep answers concise since this "
                        "is a phone call. One to three sentences max, then offer to go deeper.\n\n"
                        "VOICE rules:\n"
                        "- No markdown, no bullet points, no asterisks — they sound terrible spoken.\n"
                        "- Use contractions and a natural, relaxed tone.\n"
                        "- When vague, ask one short clarifying question.\n\n"
                        "Tools: get_current_time (call when asked the time/date), "
                        "get_weather (call when asked about weather). "
                        "For everything else, answer from knowledge."
                    ),
                }
            ],
            tools=[get_current_time_schema, get_weather_schema],
        )

        vad = SileroVADAnalyzer(
            params=VADParams(confidence=0.85, min_volume=0.6, start_secs=0.3, stop_secs=0.3)
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

        worker = PipelineWorker(
            pipeline,
            params=PipelineParams(
                enable_metrics=False,
                audio_in_sample_rate=16000,
                audio_out_sample_rate=24000,
            ),
            idle_timeout_secs=None,
        )

        runner = WorkerRunner()
        await runner.add_workers(worker)

        @transport.event_handler("on_client_connected")
        async def on_connected(transport, ws):
            await asyncio.sleep(1.0)
            print("[stream] Sending greeting…", flush=True)
            await worker.queue_frame(
                TTSSpeakFrame(
                    "Hello, Jarvis here. I'm connected over your phone call. "
                    "How can I help you today?"
                )
            )

        @transport.event_handler("on_client_disconnected")
        async def on_disconnected(transport, ws):
            print("[stream] caller disconnected", flush=True)
            await worker.queue_frame(EndFrame())

        print(f"[stream] Pipeline running — streamId={stream_id}", flush=True)
        await runner.run()

    print("[stream] Session ended.\n", flush=True)


# ─── Health check ─────────────────────────────────────────────────────────────

@app.get("/")
async def health():
    return {"status": "ok", "server_url": SERVER_URL or "NOT SET"}


if __name__ == "__main__":
    uvicorn.run("bot:app", host="0.0.0.0", port=8000, reload=False)
