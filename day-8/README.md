# Nova — AI Voice Receptionist (Acme Dental)

A production phone agent that answers real PSTN calls, holds a natural spoken
conversation, routes the caller by intent, logs every call (transcript + intent +
AI summary) to Postgres, and fires a post-call automation. It runs 24/7 on Railway —
no laptop, no tunnel in the call path.

Call it: **+91 22 6998 5969** → "Thank you for calling Acme Dental. I'm Nova, your
virtual receptionist…"

---

## What it does

- **Answers phone calls** via Plivo (PSTN → SIP/WebSocket media stream).
- **Real-time voice loop**: speech-to-text → LLM → text-to-speech, with barge-in
  (you can interrupt mid-sentence) and idle handling ("are you still there?").
- **Function calling / intent routing**: business hours, location, route-to-sales,
  route-to-support, graceful end-call.
- **Logs every call** to Postgres: caller number, intent, full transcript, and a
  1–2 sentence LLM-generated summary.
- **Post-call automation**: on hangup, POSTs the call data to an n8n webhook
  (e.g. appends a row to a Google Sheet).

---

## Architecture

```
   PSTN caller
       │  dials +91 22 6998 5969
       ▼
   ┌─────────┐   HTTP POST /answer        ┌──────────────────────────────┐
   │  Plivo  │ ─────────────────────────► │  bot.py (FastAPI on Railway) │
   │  Voice  │ ◄───────────────────────── │  returns Plivo <Stream> XML  │
   └─────────┘   bidirectional media WS    └──────────────────────────────┘
       │  wss://…/stream (audio/x-mulaw 8k)            │
       ▼                                               ▼
   ┌───────────────────────────────────────────────────────────────────┐
   │                 Pipecat pipeline (one per call)                    │
   │  Plivo serializer → VAD (Silero) → STT (ElevenLabs)                │
   │     → LLM (Groq llama-3.3-70b + function tools)                    │
   │     → TTS (ElevenLabs turbo v2.5) → back to Plivo                  │
   └───────────────────────────────────────────────────────────────────┘
       │ on hangup (guaranteed finally path)
       ├──► Groq: generate 1–2 sentence summary
       ├──► Postgres: INSERT call_logs (number, intent, transcript, summary)
       └──► n8n webhook: POST {caller_number, intent, summary} → Google Sheet
```

**Session state.** Each call is one live WebSocket = one Pipecat `LLMContext` holding
the full conversation in memory for that call (this is the "memory" that lets Nova
reference earlier turns). Durable records live in **Postgres**. There is no external
Redis in the receptionist — an earlier serverless IVR prototype (see `../day-3`) used
Upstash Redis for cross-request session storage, which the streaming model makes
unnecessary (the socket *is* the session).

---

## Tech stack

| Layer            | Choice                                              |
|------------------|-----------------------------------------------------|
| Language/runtime | Python 3.11                                         |
| Voice framework  | Pipecat 1.4.0                                        |
| Web server       | FastAPI + Uvicorn                                    |
| Telephony        | Plivo (Voice / XML application)                      |
| STT              | ElevenLabs                                           |
| LLM              | Groq — `llama-3.3-70b-versatile`                     |
| TTS              | ElevenLabs — `eleven_turbo_v2_5`                     |
| VAD / turn-taking| Silero VAD (built into Pipecat)                     |
| Database         | PostgreSQL (Railway Postgres)                        |
| Hosting          | Railway                                              |
| Automation       | n8n (self-hosted) → Google Sheets                   |

---

## Prerequisites

- **Python 3.11** (Pipecat 1.4 needs ≥3.10; 3.11 is pinned via `.python-version`).
- Accounts/keys:
  - **Plivo** — a voice-enabled phone number + Auth ID/Token.
  - **Groq** — API key.
  - **ElevenLabs** — API key + a voice ID.
  - **Railway** — for hosting + Postgres (free trial works).
- For local phone testing only: **cloudflared** (or ngrok) to expose `localhost`.

---

## Environment variables

Set these in `.env` for local runs, or in **Railway → service → Variables** in prod.
Never commit real values — `.env` is gitignored; `.env.example` is the template.

| Variable              | Required | Description                                                       |
|-----------------------|----------|-------------------------------------------------------------------|
| `ELEVENLABS_API_KEY`  | ✅       | ElevenLabs key — used for **both** STT and TTS                    |
| `ELEVENLABS_VOICE_ID` | ✅       | TTS voice (e.g. `pNInz6obpgDQGcFmaJgB`)                           |
| `GROQ_API_KEY`        | ✅       | Groq key for the LLM + post-call summary                          |
| `PLIVO_AUTH_ID`       | ✅       | Plivo Auth ID — enables programmatic auto hang-up                 |
| `PLIVO_AUTH_TOKEN`    | ✅       | Plivo Auth Token                                                  |
| `DATABASE_URL`        | ✅       | Postgres connection string (Railway Postgres reference variable) |
| `N8N_WEBHOOK_URL`     | optional | Post-call webhook; if unset, the n8n POST is skipped (no error)  |
| `SERVER_URL`          | optional | Public base URL. **Leave unset on Railway** — auto-derived from `RAILWAY_PUBLIC_DOMAIN`. Set only for local tunnel testing. |
| `PORT`                | auto     | Injected by Railway; falls back to 8000 locally                  |

---

## Run locally

```bash
cd day-8
python3.11 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env        # then fill in your keys
# For a local phone test, set SERVER_URL to your tunnel URL (below).

uvicorn bot:app --host 0.0.0.0 --port 8000
```

Health check: `curl http://localhost:8000/` → `{"status":"ok", ...}`

**To take a real call locally**, expose the server and point Plivo at it:

```bash
cloudflared tunnel --url http://localhost:8000      # copy the https URL
# set SERVER_URL=<that https url> in .env, restart uvicorn
```

Then in Plivo (see the runbook) set your number's application **Answer URL** to
`https://<tunnel>/answer` (POST). Call the number — Nova answers.

---

## Deploy on Railway

The repo ships a `Procfile`, `requirements.txt`, and `.python-version` — Railway
builds and runs it directly.

```bash
cd day-8
railway init                       # create/link a project
railway add -d postgres            # add a Postgres database
railway up                         # build + deploy this folder
railway domain                     # generate the public URL
# set the env vars in the dashboard (DATABASE_URL references the Postgres plugin)
railway logs                       # watch it boot
```

Live URL: `https://fde-day8-bot-production.up.railway.app`
Start command (from `Procfile`): `web: uvicorn bot:app --host 0.0.0.0 --port $PORT`

Full step-by-step (with Plivo wiring, verification, and troubleshooting) is in
[`../day-10/RUNBOOK.md`](../day-10/RUNBOOK.md). Endpoint reference is in
[`../day-10/API.md`](../day-10/API.md).

---

## Endpoints (summary)

| Method | Path            | Purpose                                             |
|--------|-----------------|-----------------------------------------------------|
| GET    | `/`             | Health check                                        |
| POST   | `/answer`       | Plivo answer webhook → returns `<Stream>` XML       |
| WS     | `/stream`       | Bidirectional audio media stream (Pipecat pipeline) |
| GET    | `/call-history` | Recent call logs from Postgres (`?limit=N`)         |

See [`../day-10/API.md`](../day-10/API.md) for full request/response details.

---

## Project layout

```
day-8/
├── bot.py             # the whole agent: endpoints + pipeline + logging + n8n
├── requirements.txt   # pinned deps (pipecat-ai 1.4.0, fastapi, asyncpg, …)
├── Procfile           # Railway start command
├── .python-version    # 3.11
├── .env.example       # env template (no secrets)
└── README.md          # this file
```
