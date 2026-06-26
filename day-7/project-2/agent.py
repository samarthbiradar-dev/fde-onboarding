"""Day 7 Project 2 — LiveKit voice agent (ElevenLabs STT + Groq + ElevenLabs TTS).

Run:
    python agent.py dev

Then open cloud.livekit.io → Agents → Console → select voice-agent → Start a session.
"""

import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()

# Write logs to file AND stderr so we can inspect crashes
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(sys.stderr),
        logging.FileHandler("/tmp/livekit_agent.log"),
    ],
)
logger = logging.getLogger("voice-agent")

from livekit.agents import Agent, AgentSession, JobContext, WorkerOptions, cli
from livekit.plugins import elevenlabs, groq

SYSTEM_PROMPT = """\
You are a helpful AI voice assistant. Keep responses short and conversational — \
this is a voice call, so no markdown, no bullet points, just natural speech. \
When the conversation starts, greet the user and ask how you can help.
"""


class VoiceAgent(Agent):
    def __init__(self):
        super().__init__(instructions=SYSTEM_PROMPT)

    async def on_enter(self):
        logger.info("on_enter fired")
        self.session.say("Hey! I'm your AI assistant. What can I help you with today?")


async def entrypoint(ctx: JobContext):
    logger.info(f"entrypoint — room: {ctx.room.name}")
    await ctx.connect()
    logger.info("connected to room")

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

    logger.info("starting AgentSession")
    await session.start(agent=VoiceAgent(), room=ctx.room, capture_run=True)
    logger.info("session ended")


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, agent_name="voice-agent"))
