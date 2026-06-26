# Day 9 — Edge Deploy & Automation

## Part 1 — OpenClaw (Cloudflare edge)
- **Status:** Project 1 done (OpenClaw CLI installed + runs). Projects 2–4 parked.
- **Finding:** `openclaw` (npm, v2026.6.10) is a *personal AI assistant / multi-channel
  chat gateway* — it has **no** Cloudflare Workers deploy or Plivo-XML capability.
  The standard tool for "deploy a Plivo XML endpoint to Workers" is Cloudflare **Wrangler**.
- Install: `npm i -g openclaw@latest` → `openclaw --version`

## Part 2 — N8N automation

### Where things live
| Thing | Location |
|-------|----------|
| n8n app (installed under Node 22) | `~/n8n-local/` |
| n8n data (workflows, credentials) | `~/.n8n/database.sqlite` |
| Workflow JSON exports (tracked) | `day-9/n8n-workflows/` |
| Bot → n8n integration code | `day-9/` + applied to `day-8/bot.py` |

### Why Node 22 (not the system Node 26)
n8n's native dep `sqlite3@5.1.7` has **no prebuilt binary for Node 26**, so install
falls back to a `node-gyp` compile that fails. Node 22 LTS has prebuilts → clean install.
Installed via `brew install node@22` (keg-only at `/opt/homebrew/opt/node@22`).

### Start n8n
```bash
export PATH="/opt/homebrew/opt/node@22/bin:$PATH"
cd ~/n8n-local
N8N_DIAGNOSTICS_ENABLED=false ./node_modules/.bin/n8n start
# Editor: http://localhost:5678
```

### Projects
- **P5 Install/run n8n** — editor at http://localhost:5678 ✅
- **P6 Webhook workflow** — `webhook-test` (POST /webhook/hello → returns JSON) ✅
- **P7 Post-call workflow** — `post-call`: webhook → Edit Fields → Google Sheets append ✅
- **P8 Connect bot** — Railway bot POSTs call data to n8n on hangup (via cloudflared tunnel) ✅

### Project 8 — bot integration (in `day-8/bot.py`)
- `post_to_n8n(caller_number, intent, summary, session)` POSTs to `N8N_WEBHOOK_URL`,
  called from the guaranteed `log_once()` path. Wrapped in try/except (a webhook
  failure never affects the call or DB write).
- Railway env var: `N8N_WEBHOOK_URL = https://<tunnel>.trycloudflare.com/webhook/call-ended`
- Expose local n8n: `cloudflared tunnel --url http://localhost:5678`

### ⚠️ Ephemeral tunnel
The `trycloudflare.com` quick-tunnel URL changes every run and dies when cloudflared
stops or the Mac sleeps. To resume later: restart the tunnel, copy the new URL, and
update `N8N_WEBHOOK_URL` on Railway (`railway variables --service fde-day8-bot --set ...`),
then redeploy. For a permanent URL, host n8n in the cloud or use a named cloudflared tunnel.

### Gotchas hit (and fixed)
- **Node 26 too new**: n8n's `sqlite3@5.1.7` has no Node-26 prebuilt → install via Node 22.
- **CLI-imported workflow won't activate live**: set active via `n8n update:workflow --id=.. --active=true` then **restart** n8n so it registers the production webhook.
- **Google Sheets "Column names were updated after setup"**: hand-written schema drifts from
  the live sheet — fix by re-selecting the Sheet in the node UI (forces a fresh column fetch).

### Re-import a workflow
n8n editor → top-right **⋯** menu → **Import from File** → pick a JSON in `day-9/n8n-workflows/`.
