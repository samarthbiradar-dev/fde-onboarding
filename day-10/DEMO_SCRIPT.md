# Demo Script — Nova AI Voice Receptionist (Loom, ~3–4 min)

A read-it-straight-through voiceover. Stage directions in _italics_. Aim for
conversational, not robotic. Total spoken time ≈ 3.5 min.

**Before you record, have these open in tabs:**
1. The GitHub repo (this README + `day-8/bot.py`)
2. Railway dashboard → `fde-day8-bot` service (logs view)
3. The Google Sheet `Acme Call Log`
4. Your phone, ready to dial **+91 22 6998 5969**
5. A terminal for `curl …/call-history`

---

## 0:00 — Hook (15s)

> "Hey — I'm going to show you an AI phone receptionist I built. It answers a real
> phone number, has a natural back-and-forth conversation, figures out what the
> caller wants, and logs every call with an AI-written summary — and it's running
> 24/7 in the cloud. Let me show you, then I'll call it live."

---

## 0:15 — Architecture in one breath (30s)

_Screen: the architecture diagram in the README._

> "Quick architecture. A caller dials a Plivo phone number. Plivo hits my FastAPI
> app and gets back XML that opens a two-way audio WebSocket. That audio runs through
> a Pipecat pipeline: ElevenLabs speech-to-text, a Groq Llama-3 model that does the
> thinking and calls functions, and ElevenLabs text-to-speech back to the caller.
> When the call ends, it writes the transcript, the intent, and a Groq-generated
> summary to Postgres — and fires a webhook into n8n that drops a row in a Google
> Sheet. The whole thing is deployed on Railway, so it's always on."

---

## 0:45 — The live call (90s)

_Screen: split — phone on one side, Railway logs streaming on the other._

> "Okay, let me actually call it."

_Dial **+91 22 6998 5969**. Put it on speaker._

> Nova: _"Thank you for calling Acme Dental. I'm Nova, your virtual receptionist…"_

Hit each intent — keep it snappy:

> **You:** "What are your weekend hours?"
> _(Nova answers — that's the `get_business_hours` tool.)_
>
> **You:** "And where are you located?"
> _(Nova gives the address — `get_location`.)_
>
> **You:** "I'd like to book an appointment."
> _(Nova routes to the appointments team — `route_to_sales`.)_
>
> **You:** "Actually I have a billing problem too."
> _(Nova routes to support — `route_to_support`.)_
>
> **You:** "That's all, thanks. Goodbye."
> _(Nova says goodbye and ends the call — `end_call`.)_

> "Notice it let me interrupt, it remembered the context across questions, and it
> picked the right action each time — those are real function calls, not just chat."

_Point at the Railway logs:_

> "And you can see it live in the logs here — the tool calls firing, and at the end,
> 'Call logged' with the summary."

---

## 2:15 — The data it captured (45s)

_Screen: terminal._

> "Here's what it saved. I'll hit the call-history endpoint."

```bash
curl "https://fde-day8-bot-production.up.railway.app/call-history?limit=1"
```

> "There's the row from the call I just made — the caller number, the intent, the
> **full transcript**, and a one-sentence **summary the LLM wrote**: something like
> 'Caller asked about weekend hours and booking; routed to the appointments team.'
> That's in Postgres."

_Screen: the Google Sheet._

> "And because of the post-call webhook, the same call just showed up as a new row in
> this Google Sheet — timestamp, number, intent, summary — fully automated. A
> non-technical ops person could watch calls roll in here."

---

## 3:00 — It runs 24/7 (20s)

_Screen: Railway dashboard, service "Running"._

> "Last thing — this isn't on my laptop. It's deployed on Railway with a managed
> Postgres database. The service stays up, the phone number stays answered. I can
> close my laptop and it still takes calls. Health check's green, logs are streaming."

---

## 3:20 — Close (15s)

> "So that's Nova: a real, always-on AI receptionist — Plivo for telephony, Pipecat
> orchestrating ElevenLabs and Groq, Postgres for records, n8n for automation, all on
> Railway. Code and full docs are in the repo. Thanks for watching!"

---

### Tips
- **Test the call once before recording** — networks vary; you want a clean take.
- If a tool mis-fires on camera, that's fine — say "let me rephrase," it's realistic.
- Keep the Railway logs pane visible during the call; the live tool-call lines are the
  most convincing part.
- Have the `call-history` curl already typed so you just press Enter.
