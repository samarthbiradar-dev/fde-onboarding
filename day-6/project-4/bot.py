"""Day 6 Project 4 — Production-quality AI Receptionist for Acme Dental.

Polish additions over Project 3:
  1. Barge-in  — InterruptionFrame already default in Pipecat 1.4.0; sends clearAudio
                  to Plivo so bot speech stops the instant the caller speaks.
  2. Context   — LLMContext carries full conversation history automatically.
                  System prompt reinforces that Nova should reference earlier details.
  3. Graceful end — end_call tool: Nova says goodbye, waits for TTS to finish, hangs up.
  4. Error recovery:
       - user_idle_timeout (15 s): user silent → "are you still there?"
       - on_idle_timeout (35 s): full dead air → warn once, then hang up gracefully.
       - try/except around runner.run() so no unhandled exception drops the call.

Run:
    uvicorn bot:app --host 0.0.0.0 --port 8000

Expose:
    cloudflared tunnel --url http://localhost:8000

.env keys:
    ELEVENLABS_API_KEY, GROQ_API_KEY, ELEVENLABS_VOICE_ID
    SERVER_URL, PLIVO_AUTH_ID, PLIVO_AUTH_TOKEN, DATABASE_URL
"""

import asyncio
import json
import os
import time

import aiohttp
import asyncpg
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
from pipecat.turns.user_mute.function_call_user_mute_strategy import FunctionCallUserMuteStrategy
from pipecat.turns.user_stop.turn_analyzer_user_turn_stop_strategy import (
    TurnAnalyzerUserTurnStopStrategy,
)
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from pipecat.workers.runner import WorkerRunner

app = FastAPI()

SERVER_URL = os.environ.get("SERVER_URL", "").rstrip("/")
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://localhost/calllog_db")

_call_meta: dict = {}
_db_pool = None


# ─── Database ─────────────────────────────────────────────────────────────────

async def get_db():
    global _db_pool
    if _db_pool is None:
        _db_pool = await asyncpg.create_pool(DATABASE_URL)
    return _db_pool


async def ensure_schema():
    pool = await get_db()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS call_logs (
                id SERIAL PRIMARY KEY,
                phone_number VARCHAR(20) NOT NULL,
                menu_choice VARCHAR(100) NOT NULL DEFAULT 'general_inquiry',
                timestamp TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("ALTER TABLE call_logs ADD COLUMN IF NOT EXISTS intent VARCHAR(100)")
        await conn.execute("ALTER TABLE call_logs ADD COLUMN IF NOT EXISTS transcript TEXT")
    print("[db] Schema ready", flush=True)


async def insert_call_log(phone_number: str, intent: str, transcript: str):
    try:
        pool = await get_db()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO call_logs (phone_number, menu_choice, intent, transcript) VALUES ($1, $2, $3, $4)",
                phone_number, intent, intent, transcript,
            )
        print(f"[db] Logged — from={phone_number} intent={intent} lines={transcript.count(chr(10)) + 1}", flush=True)
    except Exception as e:
        print(f"[db] ERROR: {e}", flush=True)


@app.on_event("startup")
async def startup():
    try:
        await ensure_schema()
    except Exception as e:
        print(f"[db] WARNING: could not init DB: {e}", flush=True)


# ─── Receptionist persona ─────────────────────────────────────────────────────

RECEPTIONIST_PROMPT = """\
You are Nova, the warm and professional AI receptionist for Acme Dental.

MEMORY: You remember everything said earlier in this call. If the caller mentioned their name, reason for calling, or any other detail, reference it naturally when relevant ("As you mentioned earlier, you're a new patient — let me connect you with appointments.").

YOUR JOB:
1. Greet the caller warmly.
2. Listen carefully and call the correct function AS SOON as you understand their need.
3. When the caller signals they are done (says "thanks", "that's all", "goodbye", "bye", "no more questions", or similar), ALWAYS call end_call immediately — do not keep talking.

WHICH FUNCTION TO CALL:
- get_business_hours: caller asks about hours, schedule, or when the office is open
- get_location: caller asks about address, directions, or where the office is
- route_to_sales: caller wants to book/cancel an appointment, is a new patient, asks about pricing or insurance
- route_to_support: caller has a dental emergency, billing issue, complaint, or existing patient problem
- end_call: caller is wrapping up, saying goodbye, or has no more questions

VOICE RULES (phone call — no visual rendering):
- No markdown, bullet points, or asterisks.
- Complete, natural sentences. Warm and reassuring tone.
- Keep each response to one to three sentences.
- Never reveal you are an AI. Say you are a virtual receptionist if asked.
"""


# ─── /answer ─────────────────────────────────────────────────────────────────

@app.post("/answer")
async def answer(request: Request):
    if not SERVER_URL:
        return PlainTextResponse("SERVER_URL not set in .env", status_code=500)

    form = dict(await request.form())
    print(f"\n[answer] call: {form}", flush=True)

    call_id = form.get("CallUUID") or form.get("call_uuid") or ""
    from_number = form.get("From", "unknown")
    if call_id:
        _call_meta[call_id] = {"from": from_number}

    ws_url = SERVER_URL.replace("https://", "wss://").replace("http://", "ws://")
    ws_url = f"{ws_url}/stream"

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Stream keepCallAlive="true" contentType="audio/x-mulaw;rate=8000" bidirectional="true">{ws_url}</Stream>
    <Wait length="3600"/>
</Response>"""

    print(f"[answer] streaming to {ws_url}  caller={from_number}", flush=True)
    return PlainTextResponse(xml, media_type="text/xml")


# ─── /stream ─────────────────────────────────────────────────────────────────

@app.websocket("/stream")
async def stream_endpoint(websocket: WebSocket):
    await websocket.accept()
    print("\n[stream] WebSocket connected", flush=True)

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
        print("[stream] WARNING: no start event within 10s", flush=True)
    except Exception as e:
        print(f"[stream] WARNING reading start event: {e}", flush=True)

    caller_number = _call_meta.get(call_id or "", {}).get("from", "unknown")

    # Mutable session state — worker is set after creation (late binding for tool handlers)
    session_data = {
        "intent": "general_inquiry",
        "worker": None,
        "ending": False,           # True once end_call fires — prevents double EndFrame
        "idle_warn_count": 0,      # how many times we've asked "still there?"
    }

    # ── Tool handlers ─────────────────────────────────────────────────────────

    async def handle_get_business_hours(params: FunctionCallParams) -> None:
        session_data["intent"] = "get_business_hours"
        print("  [tool] get_business_hours", flush=True)
        await params.result_callback(
            "Acme Dental is open Monday through Friday from 8 AM to 6 PM, "
            "and Saturday from 9 AM to 2 PM. We are closed on Sundays."
        )

    async def handle_get_location(params: FunctionCallParams) -> None:
        session_data["intent"] = "get_location"
        print("  [tool] get_location", flush=True)
        await params.result_callback(
            "We are at 123 Main Street, Suite 200, Springfield — "
            "in the Main Street Medical Plaza next to the pharmacy. "
            "Free parking is available behind the building."
        )

    async def handle_route_to_sales(params: FunctionCallParams) -> None:
        session_data["intent"] = "route_to_sales"
        print("  [tool] route_to_sales", flush=True)
        await params.result_callback(
            "I'll connect you with our appointments team right away. "
            "They handle new patient bookings, scheduling, and insurance questions. "
            "Please hold for just a moment."
        )

    async def handle_route_to_support(params: FunctionCallParams) -> None:
        session_data["intent"] = "route_to_support"
        print("  [tool] route_to_support", flush=True)
        await params.result_callback(
            "I'm connecting you to our patient support team right now. "
            "They handle emergencies, billing, and existing patient concerns. "
            "Please hold on."
        )

    async def handle_end_call(params: FunctionCallParams) -> None:
        session_data["intent"] = "end_call"
        session_data["ending"] = True
        print("  [tool] end_call — scheduling graceful hang-up", flush=True)
        await params.result_callback(
            "Thank you so much for calling Acme Dental. "
            "It was a pleasure helping you today. "
            "We look forward to seeing you soon. Goodbye!"
        )
        # Wait for TTS to finish speaking the goodbye, then hang up
        await asyncio.sleep(6.0)
        w = session_data.get("worker")
        if w:
            await w.queue_frame(EndFrame())

    # ── Tool schemas ───────────────────────────────────────────────────────────

    tools = [
        FunctionSchema(
            name="get_business_hours",
            description="Get Acme Dental's business hours.",
            properties={},
            required=[],
            handler=handle_get_business_hours,
        ),
        FunctionSchema(
            name="get_location",
            description="Get Acme Dental's address and directions.",
            properties={},
            required=[],
            handler=handle_get_location,
        ),
        FunctionSchema(
            name="route_to_sales",
            description="Route caller to appointments/sales team for bookings, new patients, pricing, or insurance.",
            properties={},
            required=[],
            handler=handle_route_to_sales,
        ),
        FunctionSchema(
            name="route_to_support",
            description="Route caller to support team for emergencies, billing, complaints, or existing patient issues.",
            properties={},
            required=[],
            handler=handle_route_to_support,
        ),
        FunctionSchema(
            name="end_call",
            description="End the call gracefully. Call this when the caller says goodbye, thanks, or has no more questions.",
            properties={},
            required=[],
            handler=handle_end_call,
        ),
    ]

    # ── Pipeline setup ─────────────────────────────────────────────────────────

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

    async with aiohttp.ClientSession() as aiohttp_session:
        stt = ElevenLabsSTTService(
            api_key=os.environ["ELEVENLABS_API_KEY"],
            aiohttp_session=aiohttp_session,
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
            messages=[{"role": "system", "content": RECEPTIONIST_PROMPT}],
            tools=tools,
        )

        vad = SileroVADAnalyzer(
            params=VADParams(confidence=0.6, min_volume=0.3, start_secs=0.2, stop_secs=0.8)
        )

        smart_turn = TurnAnalyzerUserTurnStopStrategy(
            turn_analyzer=LocalSmartTurnAnalyzerV3(params=SmartTurnParams(stop_secs=1.5))
        )

        context_aggregator = LLMContextAggregatorPair(
            context,
            user_params=LLMUserAggregatorParams(
                user_mute_strategies=[FunctionCallUserMuteStrategy()],
                user_turn_strategies=UserTurnStrategies(stop=[smart_turn]),
                user_idle_timeout=15.0,  # fire on_user_turn_idle after 15s silence
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
            idle_timeout_secs=35.0,        # pipeline dead-air threshold
            cancel_on_idle_timeout=False,  # handle it ourselves — don't auto-cancel
        )

        # Store worker reference so tool handlers (defined above) can reach it
        session_data["worker"] = worker

        runner = WorkerRunner()
        await runner.add_workers(worker)

        # ── [1] Barge-in — already default in Pipecat 1.4.0.
        #   VADUserStartedSpeakingFrame → broadcast_interruption() → InterruptionFrame
        #   → transport sends clearAudio to Plivo → bot speech stops instantly.
        #   No extra code needed.

        # ── [3] User silent for 15 s → check in ──────────────────────────────
        @context_aggregator.user().event_handler("on_user_turn_idle")
        async def on_user_turn_idle(aggregator):
            if session_data["ending"]:
                return
            print("[stream] user idle 15s — checking in", flush=True)
            w = session_data.get("worker")
            if w:
                await w.queue_frame(
                    TTSSpeakFrame("Hello, are you still there? Take all the time you need.")
                )

        # ── [4] Pipeline dead air for 35 s → warn once, then hang up ─────────
        @worker.event_handler("on_idle_timeout")
        async def on_idle_timeout(worker):
            if session_data["ending"]:
                return
            session_data["idle_warn_count"] += 1
            if session_data["idle_warn_count"] == 1:
                print("[stream] pipeline idle 35s — first warning", flush=True)
                await worker.queue_frame(
                    TTSSpeakFrame(
                        "I haven't heard anything for a while. "
                        "I'm still here if you need help. "
                        "Otherwise, feel free to call us back anytime."
                    )
                )
            else:
                print("[stream] pipeline idle again — hanging up gracefully", flush=True)
                session_data["ending"] = True
                await worker.queue_frame(
                    TTSSpeakFrame("Thank you for calling Acme Dental. Goodbye!")
                )
                await asyncio.sleep(4.0)
                await worker.queue_frame(EndFrame())

        # ── Greeting ───────────────────────────────────────────────────────────
        @transport.event_handler("on_client_connected")
        async def on_connected(transport, ws):
            await asyncio.sleep(1.0)
            print("[stream] Sending greeting…", flush=True)
            await worker.queue_frame(
                TTSSpeakFrame(
                    "Thank you for calling Acme Dental. "
                    "I'm Nova, your virtual receptionist. "
                    "How can I help you today?"
                )
            )

        # ── Call end — log to Postgres ─────────────────────────────────────────
        @transport.event_handler("on_client_disconnected")
        async def on_disconnected(transport, ws):
            print("[stream] caller disconnected — building transcript", flush=True)

            lines = []
            for msg in context.messages:
                role = msg.get("role", "")
                if role in ("system", "tool"):
                    continue
                content = msg.get("content") or ""
                if isinstance(content, list):
                    parts = [
                        b.get("text", "")
                        for b in content
                        if isinstance(b, dict) and b.get("type") == "text"
                    ]
                    content = " ".join(parts).strip()
                if not content:
                    continue
                prefix = "Caller" if role == "user" else "Nova"
                lines.append(f"{prefix}: {content}")

            transcript = "\n".join(lines)
            await insert_call_log(caller_number, session_data["intent"], transcript)
            print(f"[stream] Call ended — caller={caller_number} intent={session_data['intent']}", flush=True)

            if not session_data["ending"]:
                await worker.queue_frame(EndFrame())

        print(f"[stream] Pipeline running — streamId={stream_id} caller={caller_number}", flush=True)
        try:
            await runner.run()
        except Exception as e:
            print(f"[stream] Pipeline error (recovered): {e}", flush=True)

    print("[stream] Session ended.\n", flush=True)


# ─── Health check ─────────────────────────────────────────────────────────────

@app.get("/")
async def health():
    return {"status": "ok", "server_url": SERVER_URL or "NOT SET"}


if __name__ == "__main__":
    uvicorn.run("bot:app", host="0.0.0.0", port=8000, reload=False)
