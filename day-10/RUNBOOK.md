# Deployment Runbook — Nova Voice Receptionist

Everything needed to deploy, wire up, verify, and troubleshoot the bot **without the
original author**. The app lives in `day-8/`.

- **Production URL:** `https://fde-day8-bot-production.up.railway.app`
- **Phone number:** `+91 22 6998 5969` (Plivo, app `local-ivr`, id `13257634080756463`)
- **Host:** Railway project `fde-day8-bot` (service `fde-day8-bot` + `Postgres`)

---

## 0. Prerequisites

- Accounts: **Railway**, **Plivo** (with a voice number), **Groq**, **ElevenLabs**.
- Local tools: `git`, the **Railway CLI** (`brew install railway` → `railway login`).
- Keys ready: ElevenLabs API key + voice id, Groq API key, Plivo Auth ID + Token.

---

## 1. Deploy to Railway (step by step)

```bash
cd day-8

# 1. Authenticate
railway login                      # opens browser

# 2. Create & link a project
railway init --name fde-day8-bot

# 3. Add a Postgres database to the project
railway add -d postgres

# 4. Deploy the code (builds from Procfile + requirements.txt)
railway up --detach --service fde-day8-bot

# 5. Generate a public domain
railway domain --service fde-day8-bot
#    → https://fde-day8-bot-production.up.railway.app
```

> ⚠️ **Order matters.** Create the **code service first** (`railway up` into an empty
> project) *then* add Postgres. If Postgres exists first, `railway up` may attach to the
> wrong service. If services get tangled, the clean fix is `railway delete -y` and start
> over with the order above.

Start command is read from `Procfile`:
`web: uvicorn bot:app --host 0.0.0.0 --port $PORT`. The app binds `$PORT` (Railway
injects it) — do not hardcode a port.

---

## 2. Environment variables — what to set and where

Set on the **bot** service: Railway dashboard → `fde-day8-bot` → **Variables**, or via
CLI (`railway variables --service fde-day8-bot --set "KEY=value"`).

| Variable              | Where it comes from                         | Example / note                          |
|-----------------------|---------------------------------------------|-----------------------------------------|
| `ELEVENLABS_API_KEY`  | ElevenLabs dashboard                        | used for STT **and** TTS                |
| `ELEVENLABS_VOICE_ID` | ElevenLabs voice library                    | e.g. `pNInz6obpgDQGcFmaJgB`             |
| `GROQ_API_KEY`        | Groq console                                | `gsk_…`                                 |
| `PLIVO_AUTH_ID`       | Plivo console (Account)                     | enables programmatic hang-up            |
| `PLIVO_AUTH_TOKEN`    | Plivo console (Account)                     |                                         |
| `DATABASE_URL`        | **Postgres plugin** — reference variable    | set to `${{Postgres.DATABASE_URL}}`     |
| `N8N_WEBHOOK_URL`     | your n8n webhook (optional)                  | `https://<tunnel>/webhook/call-ended`   |
| `SERVER_URL`          | **leave unset** in prod                     | auto-derived from `RAILWAY_PUBLIC_DOMAIN` |

`PORT` and `RAILWAY_PUBLIC_DOMAIN` are injected by Railway automatically — don't set them.

> **`DATABASE_URL` tip:** use the reference `${{Postgres.DATABASE_URL}}` so it points at
> the internal Postgres host. To query from your laptop, use the Postgres service's
> `DATABASE_PUBLIC_URL` instead (proxy host).

---

## 3. Point the Plivo number at the deployment

You need a Plivo **Voice XML Application** whose Answer URL is the bot's `/answer`, with
your number assigned to that application.

**Dashboard route:**
1. Plivo console → **Voice → Applications (XML)** → open (or create) an application.
2. **Answer URL:** `https://fde-day8-bot-production.up.railway.app/answer` — **Method: POST**.
3. Save.
4. **Phone Numbers → your number** → set **Application** to that app → Save.

**CLI/API route** (what was used here) — update the app and assign the number:
```bash
# update the application's answer URL
curl -X POST "https://api.plivo.com/v1/Account/$PLIVO_AUTH_ID/Application/13257634080756463/" \
  -u "$PLIVO_AUTH_ID:$PLIVO_AUTH_TOKEN" \
  -d "answer_url=https://fde-day8-bot-production.up.railway.app/answer" \
  -d "answer_method=POST"

# assign the number to that application
curl -X POST "https://api.plivo.com/v1/Account/$PLIVO_AUTH_ID/Number/912269985969/" \
  -u "$PLIVO_AUTH_ID:$PLIVO_AUTH_TOKEN" \
  -d "app_id=13257634080756463"
```

> If the number was previously routed to a **Zentrunk SIP trunk** (e.g. a LiveKit
> experiment), assigning it to the XML application overrides that. To switch back, point
> the number at the trunk again.

---

## 4. Verify it's working

**a) Health check**
```bash
curl https://fde-day8-bot-production.up.railway.app/
# {"status":"ok","server_url":"https://fde-day8-bot-production.up.railway.app"}
```

**b) Answer endpoint returns Stream XML**
```bash
curl -X POST https://fde-day8-bot-production.up.railway.app/answer \
  -d "From=910000000000&CallUUID=verify-1"
# <Response><Stream … >wss://…/stream</Stream><Wait/></Response>
```

**c) Test call** — dial **+91 22 6998 5969**. Nova should greet you. Ask for hours,
then say goodbye.

**d) DB row landed**
```bash
curl "https://fde-day8-bot-production.up.railway.app/call-history?limit=1"
# or query Postgres directly:
PUBURL=$(railway variables --service Postgres --json | python3 -c "import json,sys;print(json.load(sys.stdin)['DATABASE_PUBLIC_URL'])")
psql "$PUBURL" -c "SELECT id, phone_number, intent, summary FROM call_logs ORDER BY id DESC LIMIT 5;"
```

**e) n8n automation** (if configured) — confirm a new row in the Google Sheet, or an
n8n execution marked *success*.

---

## 5. Reading logs

```bash
railway logs --service fde-day8-bot          # runtime logs (streams)
railway logs --service fde-day8-bot --build  # build logs
```

What healthy startup looks like:
```
[startup] SERVER_URL = https://fde-day8-bot-production.up.railway.app
[db] Schema ready
INFO:     Uvicorn running on http://0.0.0.0:8080
```

During a call you'll see:
```
[answer] streaming to wss://…/stream  caller=918369069820
[stream] WebSocket connected
[stream] Sending greeting…
  [tool] get_business_hours
[db] Logged — from=918369069820 intent=end_call …
[stream] Call logged (session_end) — … summary='…'
[n8n] POST 200 -> https://…/webhook/call-ended
```

---

## 6. Troubleshooting

### Call connects but it's silent (no greeting, dead air)
- **Worker not reaching `/stream`.** Check logs for `[stream] WebSocket connected`. If
  absent, the WS never opened — verify the `/answer` XML host is correct (it must be the
  Railway `wss://…/stream`, not localhost/an old tunnel).
- **Crash building the pipeline.** Look for a `Traceback` right after the WS connects —
  usually a missing/invalid API key (ElevenLabs/Groq). Fix the env var, redeploy.
- **Wrong Answer URL still cached.** Confirm the Plivo application's Answer URL is the
  current Railway domain (Plivo "Voice logs" show the URL it called).
- **Old deploy serving.** `railway logs` should show a recent `Uvicorn running`. Redeploy
  with `railway up` if stale.

### Audio is garbled / robotic / chipmunk
- **Sample-rate mismatch.** Plivo sends μ-law **8 kHz**; the pipeline expects
  `audio_in_sample_rate=16000`, `audio_out_sample_rate=24000`, `add_wav_header=False`,
  with the `PlivoFrameSerializer`. Don't change these unless you also change the Stream
  `contentType`. Garbled audio almost always means one of these was edited.

### "Env var missing" / KeyError on boot
- The app reads keys with `os.environ[...]`; a missing one crashes the worker when a
  call starts. Check what's set: `railway variables --service fde-day8-bot`. Add the
  missing key, and confirm `DATABASE_URL` uses `${{Postgres.DATABASE_URL}}`.

### DB not logging (no new rows)
- Check logs for `[db] ERROR:` — usually a bad `DATABASE_URL`.
- Confirm the row path runs: you should see `Call logged (session_end)` even if the
  caller hangs up (logging is on a guaranteed `finally` path, not only on disconnect).
- Verify connectivity: `psql "$DATABASE_PUBLIC_URL" -c "select 1;"`.
- Confirm the table exists (auto-created on boot): `\d call_logs`.

### Summary is empty / `NULL`
- The summary calls Groq directly over HTTP. Groq sits behind Cloudflare, which **403s
  requests with no `User-Agent`** (error 1010). The bot sets `User-Agent: fde-day8-bot/1.0`
  — if you refactor that call, keep the header or summaries silently come back empty.

### n8n webhook not firing
- `N8N_WEBHOOK_URL` must be **publicly reachable** from Railway. A local n8n needs a
  tunnel (`cloudflared tunnel --url http://localhost:5678`). Quick-tunnel URLs are
  **ephemeral** — when the tunnel restarts, update `N8N_WEBHOOK_URL` and redeploy.
- The n8n workflow must be **Active**; check logs for `[n8n] POST 200`.
- A failed POST never breaks the call or DB write (it's wrapped in try/except).

### Plivo call fails immediately / "application error"
- Plivo **Voice Logs** (console) show the exact Answer URL it hit and the HTTP result.
  A non-200 there means the Answer URL is wrong or the service is down — re-check §3/§4.

### Build fails on Railway
- Pin Python via `.python-version` (3.11). Pipecat's native deps need a supported
  Python; very new majors can lack prebuilt wheels.
- Read `railway logs --build` for the failing package.

---

## 7. Redeploy / rollback

```bash
# redeploy current code
cd day-8 && railway up --detach --service fde-day8-bot

# change a variable then redeploy
railway variables --service fde-day8-bot --set "N8N_WEBHOOK_URL=https://new/webhook/call-ended"
railway up --detach --service fde-day8-bot
```
Rollback: Railway dashboard → service → **Deployments** → pick a previous successful
deploy → **Redeploy**.
