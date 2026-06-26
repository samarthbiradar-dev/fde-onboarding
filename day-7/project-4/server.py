"""Project 4 — Plivo XML bridge: PSTN call → LiveKit SIP.

Bypasses Zentrunk. Plivo calls this answer_url and gets back XML
that dials directly into LiveKit's SIP inbound endpoint.

Run:
    python server.py

Expose:
    cloudflared tunnel --url http://localhost:8001

Then set +912269985969 answer URL in Plivo console to:
    https://<tunnel>.trycloudflare.com/answer
"""

import os
from dotenv import load_dotenv
load_dotenv()
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse

app = FastAPI()

LIVEKIT_SIP_DOMAIN = "sip.livekit.cloud"
PLIVO_NUMBER = os.environ.get("PLIVO_NUMBER", "+912269985969")


@app.post("/answer")
async def answer(request: Request):
    form = dict(await request.form())
    caller = form.get("From", "unknown")
    print(f"[answer] incoming call from {caller}")

    # Bridge PSTN call straight into LiveKit SIP inbound
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Dial>
        <SIP>sip:{PLIVO_NUMBER.lstrip('+')}@{LIVEKIT_SIP_DOMAIN}</SIP>
    </Dial>
</Response>"""
    print(f"[answer] forwarding to {LIVEKIT_SIP_DOMAIN}")
    return PlainTextResponse(xml, media_type="text/xml")


@app.get("/")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8001, reload=False)
