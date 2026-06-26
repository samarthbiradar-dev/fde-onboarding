"""Day 7 Project 5 — LiveKit AI Receptionist (parity with Day 6 Pipecat bot).

Same pipeline: ElevenLabs STT + Groq + ElevenLabs TTS
Same features: greeting, intent detection, function calls, Postgres transcript logging.

Run:
    python agent.py dev          # browser test via LiveKit Console
    python agent.py start        # production (SIP calls from Plivo)
"""

import asyncio
import logging
import os
import sys

import asyncpg
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("receptionist")

from livekit import api
from livekit.agents import Agent, AgentSession, JobContext, WorkerOptions, cli, function_tool
from livekit.plugins import elevenlabs, groq

# ── Postgres ──────────────────────────────────────────────────────────────────

_db_pool = None


async def get_db():
    global _db_pool
    if _db_pool is None:
        _db_pool = await asyncpg.create_pool(os.environ["DATABASE_URL"])
    return _db_pool


async def ensure_schema():
    pool = await get_db()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS call_logs (
                id SERIAL PRIMARY KEY,
                phone_number VARCHAR(20) NOT NULL,
                menu_choice VARCHAR(100) NOT NULL DEFAULT 'general_inquiry',
                intent VARCHAR(100),
                transcript TEXT,
                timestamp TIMESTAMPTZ DEFAULT NOW()
            )
        """)


async def log_call(phone_number: str, intent: str, transcript: str):
    try:
        pool = await get_db()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO call_logs (phone_number, menu_choice, intent, transcript) VALUES ($1, $2, $3, $4)",
                phone_number, intent, intent, transcript,
            )
        logger.info(f"Logged call — from={phone_number} intent={intent}")
    except Exception as e:
        logger.error(f"DB log error: {e}")


# ── Persona ───────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are Nova, the warm and professional AI receptionist for Acme Dental.

MEMORY: You remember everything said earlier in this call. If the caller mentioned \
their name, reason for calling, or any other detail, reference it naturally when relevant.

YOUR JOB:
1. Greet the caller warmly on the first turn.
2. Listen carefully and call the correct function AS SOON as you understand their need.
3. When the caller signals they are done (says "thanks", "goodbye", "bye", "no more \
questions", or similar), ALWAYS call end_call immediately.

WHICH FUNCTION TO CALL:
- get_business_hours: caller asks about hours, schedule, or when the office is open
- get_location: caller asks about address, directions, or where the office is
- route_to_sales: caller wants to book/cancel an appointment, is a new patient, \
asks about pricing or insurance
- route_to_support: caller has a dental emergency, billing issue, complaint, or \
existing patient problem
- end_call: caller is wrapping up, saying goodbye, or has no more questions

VOICE RULES (phone call — no visual rendering):
- No markdown, bullet points, or asterisks.
- Complete, natural sentences. Warm and reassuring tone.
- Keep each response to one to three sentences.
- Never reveal you are an AI. Say you are a virtual receptionist if asked.
"""


# ── Agent ─────────────────────────────────────────────────────────────────────

class ReceptionistAgent(Agent):
    def __init__(self, caller_number: str):
        super().__init__(instructions=SYSTEM_PROMPT)
        self._caller_number = caller_number
        self._intent = "general_inquiry"

    async def on_enter(self):
        self.session.say(
            "Thank you for calling Acme Dental. "
            "I'm Nova, your virtual receptionist. "
            "How can I help you today?"
        )

    @function_tool
    async def get_business_hours(self) -> str:
        """Get Acme Dental's business hours."""
        self._intent = "get_business_hours"
        return (
            "Acme Dental is open Monday through Friday from 8 AM to 6 PM, "
            "and Saturday from 9 AM to 2 PM. We are closed on Sundays."
        )

    @function_tool
    async def get_location(self) -> str:
        """Get Acme Dental's address and directions."""
        self._intent = "get_location"
        return (
            "We are at 123 Main Street, Suite 200, Springfield — "
            "in the Main Street Medical Plaza next to the pharmacy. "
            "Free parking is available behind the building."
        )

    @function_tool
    async def route_to_sales(self) -> str:
        """Route caller to appointments/sales team for bookings, new patients, pricing, or insurance."""
        self._intent = "route_to_sales"
        return (
            "I'll connect you with our appointments team right away. "
            "They handle new patient bookings, scheduling, and insurance questions. "
            "Please hold for just a moment."
        )

    @function_tool
    async def route_to_support(self) -> str:
        """Route caller to support team for emergencies, billing, complaints, or existing patient issues."""
        self._intent = "route_to_support"
        return (
            "I'm connecting you to our patient support team right now. "
            "They handle emergencies, billing, and existing patient concerns. "
            "Please hold on."
        )

    @function_tool
    async def end_call(self) -> str:
        """End the call gracefully when the caller says goodbye or has no more questions."""
        self._intent = "end_call"
        # Disconnect the SIP participant after TTS finishes
        asyncio.create_task(self._graceful_disconnect())
        return (
            "Thank you so much for calling Acme Dental. "
            "It was a pleasure helping you today. "
            "We look forward to seeing you soon. Goodbye!"
        )

    async def _graceful_disconnect(self):
        await asyncio.sleep(6.0)
        try:
            lk = api.LiveKitAPI(
                url=os.environ["LIVEKIT_URL"],
                api_key=os.environ["LIVEKIT_API_KEY"],
                api_secret=os.environ["LIVEKIT_API_SECRET"],
            )
            await lk.room.remove_participant(
                api.RoomParticipantIdentity(
                    room=self.session.room.name,
                    identity=self._caller_number,
                )
            )
            await lk.aclose()
        except Exception as e:
            logger.warning(f"Could not remove participant: {e}")

    def build_transcript(self) -> str:
        lines = []
        for item in self.session.history.items:
            role = getattr(item, "role", "")
            if role not in ("user", "assistant"):
                continue
            content = ""
            if hasattr(item, "text_content"):
                content = item.text_content or ""
            elif hasattr(item, "content"):
                content = str(item.content or "")
            if not content.strip():
                continue
            prefix = "Caller" if role == "user" else "Nova"
            lines.append(f"{prefix}: {content.strip()}")
        return "\n".join(lines)


# ── Entrypoint ────────────────────────────────────────────────────────────────

async def entrypoint(ctx: JobContext):
    logger.info(f"Job started — room: {ctx.room.name}")
    await ctx.connect()

    # Detect caller number from SIP participant identity (falls back to "unknown")
    caller_number = "unknown"
    for pid, participant in ctx.room.remote_participants.items():
        if participant.identity.startswith("+") or participant.identity.startswith("sip"):
            caller_number = participant.identity
            break
    logger.info(f"Caller: {caller_number}")

    agent = ReceptionistAgent(caller_number=caller_number)

    session = AgentSession(
        stt=elevenlabs.STT(api_key=os.environ["ELEVENLABS_API_KEY"]),
        llm=groq.LLM(
            model="llama-3.3-70b-versatile",
            api_key=os.environ["GROQ_API_KEY"],
        ),
        tts=elevenlabs.TTS(
            api_key=os.environ["ELEVENLABS_API_KEY"],
            voice_id=os.environ.get("ELEVENLABS_VOICE_ID", "pNInz6obpgDQGcFmaJgB"),
            model="eleven_turbo_v2_5",
        ),
    )

    # Log call when session ends
    @session.on("close")
    def on_close():
        transcript = agent.build_transcript()
        asyncio.create_task(
            log_call(caller_number, agent._intent, transcript)
        )

    await session.start(agent=agent, room=ctx.room, capture_run=True)
    logger.info("Session ended")


# ── Worker ────────────────────────────────────────────────────────────────────

async def _startup():
    try:
        await ensure_schema()
        logger.info("DB schema ready")
    except Exception as e:
        logger.warning(f"DB not available: {e} — logging disabled")


if __name__ == "__main__":
    asyncio.run(_startup())
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, agent_name="receptionist"))
