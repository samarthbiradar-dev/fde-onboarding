"""Day 6 Project 1 — Basic Plivo WebSocket server.

Plivo calls your number → hits /answer → returns XML that tells Plivo to
stream call audio to /stream (WebSocket).  The server logs every event and
counts incoming audio packets so you can verify the stream is live.

Run:
    uvicorn server:app --host 0.0.0.0 --port 8000 --reload

Expose publicly (Plivo can't reach localhost):
    ngrok http 8000

Then set your Plivo number's Answer URL to:
    https://<ngrok-id>.ngrok.io/answer   (HTTP POST)
"""

import base64
import json
import os

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse

load_dotenv()

app = FastAPI()

# Public base URL — set SERVER_URL in .env or pass via environment.
# Used to build the wss:// address returned in the XML.
SERVER_URL = os.environ.get("SERVER_URL", "").rstrip("/")


# ─── /answer — Plivo calls this when the call is answered ────────────────────

@app.post("/answer")
async def answer(request: Request):
    """Return Plivo XML that opens a media stream to /stream."""
    if not SERVER_URL:
        return PlainTextResponse(
            "SERVER_URL not set in .env — can't build stream URL.", status_code=500
        )

    # Log all params Plivo sends so we can see CallUUID and other fields.
    form = await request.form()
    params = dict(form)
    print(f"\n[answer] Incoming call params: {params}", flush=True)

    # Replace https:// with wss:// for the WebSocket address.
    ws_url = SERVER_URL.replace("https://", "wss://").replace("http://", "ws://")
    ws_url = f"{ws_url}/stream"

    callback_url = f"{SERVER_URL}/stream-status"
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Stream keepCallAlive="true" contentType="audio/x-mulaw;rate=8000" statusCallbackUrl="{callback_url}" statusCallbackMethod="POST">{ws_url}</Stream>
    <Wait length="3600"/>
</Response>"""

    print(f"[answer] Streaming to {ws_url}", flush=True)
    return PlainTextResponse(xml, media_type="text/xml")


# ─── /stream — Plivo streams audio here over WebSocket ───────────────────────

@app.websocket("/stream")
async def stream(ws: WebSocket):
    """Receive and log Plivo media stream events."""
    await ws.accept()
    print("\n[stream] WebSocket connected — waiting for audio…", flush=True)

    packet_count = 0
    byte_count = 0
    stream_sid = None

    try:
        while True:
            data = await ws.receive()
            # Plivo sends JSON text; handle binary fallback just in case
            if data["type"] == "websocket.receive":
                raw = data.get("text") or data.get("bytes", b"").decode("utf-8", errors="replace")
            else:
                continue
            if not raw:
                continue
            try:
                msg = json.loads(raw)
            except Exception:
                print(f"[stream] non-JSON frame ({len(raw)} bytes)", flush=True)
                continue
            event = msg.get("event", "unknown")

            if event == "start":
                meta = msg.get("start", {})
                stream_sid = meta.get("streamSid") or msg.get("streamSid", "?")
                call_sid = meta.get("callSid", "?")
                tracks = meta.get("tracks", [])
                print(
                    f"[stream] START  streamSid={stream_sid}  callSid={call_sid}  tracks={tracks}",
                    flush=True,
                )

            elif event == "media":
                media = msg.get("media", {})
                payload_b64 = media.get("payload", "")
                audio_bytes = len(base64.b64decode(payload_b64)) if payload_b64 else 0
                packet_count += 1
                byte_count += audio_bytes

                # Log every 50 packets so the terminal doesn't flood.
                if packet_count % 50 == 0:
                    print(
                        f"[stream] MEDIA  packets={packet_count}  "
                        f"total_bytes={byte_count}  chunk_bytes={audio_bytes}",
                        flush=True,
                    )

            elif event == "stop":
                print(
                    f"[stream] STOP   packets_received={packet_count}  "
                    f"total_bytes={byte_count}",
                    flush=True,
                )
                break

            else:
                print(f"[stream] {event.upper()}  {msg}", flush=True)

    except WebSocketDisconnect:
        print(
            f"[stream] WebSocket disconnected — "
            f"packets={packet_count}  bytes={byte_count}",
            flush=True,
        )
    except Exception as e:
        print(f"[stream] ERROR: {e}", flush=True)
    finally:
        print("[stream] Session ended.\n", flush=True)


# ─── /stream-status — Plivo POSTs stream lifecycle events here ───────────────

@app.post("/stream-status")
async def stream_status(request: Request):
    body = await request.json()
    print(f"\n[stream-status] {body}\n", flush=True)
    return {"status": "ok"}


# ─── Health check ─────────────────────────────────────────────────────────────

@app.get("/")
async def health():
    return {"status": "ok", "server_url": SERVER_URL or "NOT SET"}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=True)
