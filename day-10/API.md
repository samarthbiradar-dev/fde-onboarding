# API Documentation — Nova Voice Receptionist

Base URL (production): `https://fde-day8-bot-production.up.railway.app`
Local: `http://localhost:8000`

The service is a FastAPI app (`day-8/bot.py`). It exposes 4 HTTP/WS endpoints and
makes 1 outbound webhook call. Most of the "API" is driven by **Plivo** during a
phone call, not by humans.

---

## Endpoint index

| Method | Path            | Auth | Purpose                                          |
|--------|-----------------|------|--------------------------------------------------|
| GET    | `/`             | none | Health check                                     |
| POST   | `/answer`       | none¹| Plivo answer webhook → returns call-control XML  |
| WS     | `/stream`       | none¹| Bidirectional audio media stream (the live call) |
| GET    | `/call-history` | none | Recent call logs from Postgres                   |
| POST   | `→ N8N_WEBHOOK_URL` | n/a | **Outbound** post-call automation trigger    |

¹ No app-level auth; Plivo is the only intended caller. The optional `PLIVO_AUTH_ID/
TOKEN` are used by the bot to call Plivo's API (auto hang-up), not to authenticate
inbound requests.

---

## 1. `GET /` — Health check

Liveness probe. Confirms the process is up and which public URL it resolved.

**Request:** none.

**Response `200 application/json`:**
```json
{ "status": "ok", "server_url": "https://fde-day8-bot-production.up.railway.app" }
```

```bash
curl https://fde-day8-bot-production.up.railway.app/
```

---

## 2. `POST /answer` — Plivo answer webhook

Called by Plivo the moment a call connects (configured as the application's **Answer
URL**). The bot replies with Plivo XML telling Plivo to open a **bidirectional media
WebSocket** back to `/stream`.

**Request** — `application/x-www-form-urlencoded` (Plivo standard call params), e.g.:

| Field       | Example                  | Notes                          |
|-------------|--------------------------|--------------------------------|
| `From`      | `918369069820`           | Caller number                  |
| `To`        | `912269985969`           | Your Plivo number              |
| `CallUUID`  | `0eea9843-…`             | Plivo call id (used for hang-up)|
| `Direction` | `inbound`                |                                |
| `CallStatus`| `ringing`                |                                |

**Response `200 text/xml`** — the Stream XML (the `wss` host is auto-derived from
`RAILWAY_PUBLIC_DOMAIN`/`SERVER_URL`):
```xml
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Stream keepCallAlive="true" contentType="audio/x-mulaw;rate=8000" bidirectional="true">wss://fde-day8-bot-production.up.railway.app/stream</Stream>
    <Wait length="3600"/>
</Response>
```

**Errors:** `500` if neither `SERVER_URL` nor `RAILWAY_PUBLIC_DOMAIN` is available
(can't build the `wss` URL).

```bash
curl -X POST https://fde-day8-bot-production.up.railway.app/answer \
  -d "From=918369069820&To=912269985969&CallUUID=test-123"
```

---

## 3. `WS /stream` — Media stream (the live conversation)

The actual voice call. Plivo connects here as a WebSocket and streams μ-law 8 kHz
audio in both directions. This endpoint runs one **Pipecat pipeline per call**.

**Protocol:** Plivo Media Streaming over WebSocket.
- First message: a JSON `start` event (`streamId`, `callId`).
- Then continuous base64 audio frames in/out.
- Serialized/deserialized by Pipecat's `PlivoFrameSerializer`.

**Pipeline inside the socket:**
`transport.input → VAD (Silero) → STT (ElevenLabs) → LLM (Groq + tools) → TTS
(ElevenLabs) → transport.output`.

**Function tools the LLM can call** (these are not HTTP endpoints — they execute
in-process and shape the conversation):

| Tool                 | Trigger (intent)                                  |
|----------------------|---------------------------------------------------|
| `get_business_hours` | hours / when open                                 |
| `get_location`       | address / directions                              |
| `route_to_sales`     | booking, new patient, pricing, insurance          |
| `route_to_support`   | emergency, billing, complaint, existing patient   |
| `end_call`           | caller says goodbye / no more questions           |

Not for manual/curl use — it requires the Plivo media handshake.

---

## 4. `GET /call-history` — Recent call logs

Returns the most recent rows from the `call_logs` Postgres table, newest first.

**Query params:** `limit` (int, 1–100, default 20).

**Response `200 application/json`:**
```json
{
  "count": 1,
  "calls": [
    {
      "id": 7,
      "phone_number": "918369069820",
      "intent": "end_call",
      "summary": "Caller inquired about weekend hours…; routed to the appointments team.",
      "transcript": "Nova: Thank you for calling Acme Dental…\nCaller: …",
      "timestamp": "2026-06-26T12:27:29.519240+00:00"
    }
  ]
}
```

On DB error returns `{ "error": "...", "count": 0, "calls": [] }` (still `200`).

```bash
curl "https://fde-day8-bot-production.up.railway.app/call-history?limit=5"
```

---

## 5. Outbound — Post-call automation webhook

After every call ends, the bot **POSTs** call data to `N8N_WEBHOOK_URL` (if set). This
is what drives the n8n workflow (e.g. append a Google Sheet row). Skipped silently if
the env var is unset; failures are caught and never affect the call or DB write.

**Request the bot sends** — `application/json`:
```json
{
  "caller_number": "918369069820",
  "intent": "end_call",
  "summary": "Caller asked about weekend hours; routed to booking."
}
```

**Consumer:** the n8n `post-call` workflow — webhook `POST /webhook/call-ended`
→ Edit Fields (adds `timestamp`) → Google Sheets *Append Row*. n8n responds
`{"message":"Workflow was started"}`.

---

## Plivo XML flow

```
Caller dials +91 22 6998 5969
        │
        ▼
Plivo looks up the number's Application → Answer URL
        │  POST /answer  (call metadata)
        ▼
bot returns <Response><Stream bidirectional="true">wss://…/stream</Stream><Wait/></Response>
        │
        ▼
Plivo opens WS to /stream  ──►  audio flows both ways  ──►  Pipecat pipeline
        │
        ▼
end_call tool OR caller hangs up  ──►  Plivo closes the stream
```

---

## Call lifecycle (end to end)

1. **Connect** — Plivo `POST /answer`; bot returns Stream XML.
2. **Stream open** — Plivo opens `WS /stream`; bot reads the `start` event, captures
   the caller number, builds the Pipecat pipeline.
3. **Greeting** — on client-connected, Nova greets the caller.
4. **Conversation** — VAD → STT → Groq (with tools) → TTS, turn by turn; barge-in and
   idle timeouts handled.
5. **End** — `end_call` tool (bot-initiated) or caller hangup.
6. **Logging (guaranteed `finally` path)** — build transcript → Groq generates a
   1–2 sentence summary → `INSERT` into `call_logs` → POST to `N8N_WEBHOOK_URL`.
   This path runs whether the bot or the caller ended the call (idempotent guard).

---

## Data model — `call_logs` (Postgres)

| Column        | Type          | Notes                                   |
|---------------|---------------|-----------------------------------------|
| `id`          | serial PK     |                                         |
| `phone_number`| varchar(20)   | caller number                           |
| `menu_choice` | varchar(100)  | legacy field; mirrors `intent`          |
| `intent`      | varchar(100)  | last detected intent / tool             |
| `transcript`  | text          | full `Caller:`/`Nova:` transcript       |
| `summary`     | text          | Groq-generated 1–2 sentence recap       |
| `timestamp`   | timestamptz   | defaults to `NOW()`                      |

Schema is created/migrated automatically on startup (`CREATE TABLE IF NOT EXISTS` +
`ADD COLUMN IF NOT EXISTS`).
