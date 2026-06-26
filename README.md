# FDE Accelerated Onboarding

A two-week build log culminating in **Nova** — a production AI voice receptionist that
answers real phone calls, holds a natural conversation, routes by intent, logs every
call with an AI summary, and runs 24/7 on Railway.

> **📞 Capstone:** [`day-8/`](./day-8/) — the deployed receptionist. Full docs in
> [`day-10/`](./day-10/): [README](./day-8/README.md) · [API](./day-10/API.md) ·
> [Demo script](./day-10/DEMO_SCRIPT.md) · [Runbook](./day-10/RUNBOOK.md).

---

## The arc

The two weeks build from CLI tooling → web/telephony → serverless IVR → LLMs →
real-time voice → telephony integration → cloud deployment → automation → docs.

| Day | Theme | Highlights |
|-----|-------|------------|
| **1** | Tooling & Plivo basics | Folder-stats CLI; Plivo account health checker |
| **2** | Web, DB, sessions | Flask webhook server; Postgres call log; Redis sessions; IVR system |
| **3** | Serverless IVR | Flask IVR on Vercel; Upstash Redis sessions; Neon Postgres call-log API; IVR health monitor |
| **4** | LLMs (Groq) | Single-call & streaming Groq; terminal chatbot; function-calling chatbot; first voice pipeline |
| **5** | Local voice bots (Pipecat) | Local pipeline → interruptions → smart-turn → latency tracking → function calling |
| **6** | Telephony voice agent | Pipecat receptionist over a Plivo WebSocket (the basis for Nova) |
| **7** | LiveKit voice agents | Browser agent; SIP inbound trunk; Plivo→LiveKit via Zentrunk; full receptionist |
| **8** | **Cloud deploy (capstone)** | **Nova on Railway** — `$PORT` binding, managed Postgres, Groq summaries, n8n hook |
| **9** | Edge & automation | OpenClaw CLI; **n8n** webhook + post-call → Google Sheets automation |
| **10** | Documentation | This README + project README, API docs, demo script, deployment runbook |

---

## The capstone system (Day 8 + 9)

```
PSTN caller → Plivo → POST /answer → <Stream> XML → WS /stream
   → Pipecat: ElevenLabs STT → Groq LLM (+ tools) → ElevenLabs TTS → caller
   → on hangup: Groq summary → Postgres call_logs → n8n webhook → Google Sheet
   (deployed on Railway, always on)
```

- **Telephony:** Plivo · **STT/TTS:** ElevenLabs · **LLM:** Groq `llama-3.3-70b`
- **Framework:** Pipecat 1.4 (FastAPI/Uvicorn) · **DB:** Railway Postgres
- **Automation:** n8n → Google Sheets · **Host:** Railway

Details: [`day-8/README.md`](./day-8/README.md).

---

## Documentation (Day 10)

| Doc | What it covers |
|-----|----------------|
| [Project README](./day-8/README.md) | What it is, architecture, stack, setup, env vars, run, deploy |
| [API.md](./day-10/API.md) | Every endpoint (method/URL/I/O), Plivo XML flow, call lifecycle, data model |
| [DEMO_SCRIPT.md](./day-10/DEMO_SCRIPT.md) | 3–4 min Loom voiceover for a live demo |
| [RUNBOOK.md](./day-10/RUNBOOK.md) | Deploy steps, env vars, Plivo wiring, verification, logs, troubleshooting |

---

## Getting started

```bash
git clone https://github.com/samarthbiradar-dev/fde-onboarding.git
cd fde-onboarding
```

Each `day-N/` (and most `project-*/`) folder has its own README / `.env.example`.
Secrets are never committed — copy `.env.example` to `.env` and fill in your own keys.

To run the capstone locally, start at [`day-8/README.md`](./day-8/README.md).

---

## Security note

No live credentials are in this repo. All `.env` files are gitignored; only
`.env.example` templates (placeholders) are tracked. If you fork this, supply your own
Plivo / Groq / ElevenLabs / Railway keys.
