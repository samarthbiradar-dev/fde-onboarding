# Day 2 — Project 4: IVR Phone System

Production-ready local Interactive Voice Response (IVR) system built on Flask + Plivo XML + Redis session state + PostgreSQL call history.

## Architecture

```
Plivo (inbound call)
       │
       ▼ POST /api/voice/inbound          ← Answer URL (in Plivo dashboard)
  Flask app
       │  ┌─ Redis: create ivr_session:{CallUUID}
       │
       ▼ POST /api/voice/menu-selection   ← GetDigits action URL
  Digit routing
       │  ┌─ Redis: update session (menu_depth, menu_choice)
       │  ├─ "1" → Sales  → Hangup
       │  ├─ "2" → Support → Hangup
       │  ├─ "3" → Read-back number → Hangup
       │  └─ other → "Invalid selection" → Redirect → /api/voice/inbound
       │
       ▼ POST /api/voice/call-ended       ← Hangup URL (in Plivo dashboard)
  Persist to PostgreSQL
       │  ┌─ Read menu_choice from Redis
       │  ├─ DELETE Redis session
       │  └─ INSERT call_logs row

GET /call-history  ← HTML dashboard (or ?format=json)
GET /health        ← Redis + PostgreSQL connectivity check
```

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/voice/inbound` | Plivo Answer URL — initialises session, serves main menu |
| POST | `/api/voice/menu-selection` | Plivo GetDigits action — routes digit to sales/support/readback |
| POST | `/api/voice/call-ended` | Plivo Hangup URL — writes CallLog to PostgreSQL |
| GET | `/call-history` | HTML call history dashboard (`?format=json` for JSON) |
| GET | `/health` | Redis + PostgreSQL connectivity check |

## Setup

### 1. PostgreSQL

```bash
# Create the database (one time only)
createdb ivr_db
```

### 2. Redis

```bash
brew install redis        # if not already installed
brew services start redis
redis-cli ping            # should return PONG
```

### 3. Environment

```bash
cp .env.example .env
# Edit .env — fill in BASE_URL after step 5 (ngrok)
```

### 4. Python dependencies

```bash
pip install -r requirements.txt
```

### 5. Create database tables

```bash
python3 create_db.py
# Output: Tables created successfully: call_logs
```

### 6. Run the server

```bash
python3 app.py
# Server starts at http://localhost:5003
```

### 7. ngrok tunnel (so Plivo can reach your local machine)

```bash
ngrok http 5003
# Copy the https://xxxx.ngrok-free.dev URL
```

Edit `.env` and set:
```
BASE_URL=https://xxxx.ngrok-free.dev
```

Then restart `app.py` so it picks up the new `BASE_URL`.

### 8. Configure Plivo

In the [Plivo Console](https://console.plivo.com):
1. Go to **Phone Numbers** → your number → **Edit**
2. Make sure the number is **not** attached to a Plivo Application — set it to direct URL mode
3. Set **Answer URL**: `https://xxxx.ngrok-free.dev/api/voice/inbound` — method **POST**
4. Set **Hangup URL**: `https://xxxx.ngrok-free.dev/api/voice/call-ended` — method **POST**
5. Save

---

## Local Testing (no real phone needed)

All Plivo webhooks are form-encoded POST requests. You can simulate every step with `curl`.

### Step 1 — Simulate inbound call (get the menu XML)

```bash
curl -s -X POST http://localhost:5003/api/voice/inbound \
  -d "CallUUID=test-uuid-001" \
  -d "From=%2B14151234567" \
  -d "To=%2B18005550100" \
  -d "CallStatus=in-progress"
```

Expected: valid Plivo XML with `<GetDigits>` containing a `<Speak>` menu.

### Step 2a — Simulate pressing "1" (Sales)

```bash
curl -s -X POST http://localhost:5003/api/voice/menu-selection \
  -d "CallUUID=test-uuid-001" \
  -d "Digits=1" \
  -d "From=%2B14151234567" \
  -d "To=%2B18005550100"
```

Expected: `<Speak>Connecting you to our Sales team...</Speak><Hangup />`

### Step 2b — Simulate pressing "2" (Support)

```bash
curl -s -X POST http://localhost:5003/api/voice/menu-selection \
  -d "CallUUID=test-uuid-001" \
  -d "Digits=2" \
  -d "From=%2B14151234567"
```

Expected: `<Speak>Connecting you to Technical Support...</Speak><Hangup />`

### Step 2c — Simulate pressing "3" (Number read-back)

```bash
curl -s -X POST http://localhost:5003/api/voice/menu-selection \
  -d "CallUUID=test-uuid-001" \
  -d "Digits=3" \
  -d "From=%2B14151234567"
```

Expected: `<Speak>Your phone number is 1, 4, 1, 5, 1, 2, 3, 4, 5, 6, 7.</Speak>`

### Step 2d — Simulate invalid digit (loop)

```bash
curl -s -X POST http://localhost:5003/api/voice/menu-selection \
  -d "CallUUID=test-uuid-001" \
  -d "Digits=9" \
  -d "From=%2B14151234567"
```

Expected: `<Speak>Invalid selection. Let's try again.</Speak><Redirect ...>`

### Step 3 — Simulate call hangup (writes to PostgreSQL)

```bash
curl -s -X POST http://localhost:5003/api/voice/call-ended \
  -d "CallUUID=test-uuid-001" \
  -d "From=%2B14151234567" \
  -d "To=%2B18005550100" \
  -d "CallStatus=completed" \
  -d "Duration=45"
```

Expected: `{"status": "ok"}`

### Step 4 — View call history dashboard

Open in browser: http://localhost:5003/call-history

Or as JSON:
```bash
curl http://localhost:5003/call-history?format=json
```

### Verify Redis session state

```bash
redis-cli

# List active IVR sessions
KEYS ivr_session:*

# Inspect a specific session
GET ivr_session:test-uuid-001

# Check TTL (seconds remaining)
TTL ivr_session:test-uuid-001
```

### Health check

```bash
curl http://localhost:5003/health
# {"status": "OK", "redis": "connected", "postgres": "connected", "base_url": "..."}
```

---

## IVR Menu Map

```
Caller dials your Plivo number
        │
        ▼ [Main Menu]
  "Press 1 for Sales
   Press 2 for Technical Support
   Press 3 to hear your number"
        │
   ┌────┼────┬──────────┐
   1    2    3          other/timeout
   │    │    │              │
Sales Support Read-back  "Invalid. Try again."
 TTS   TTS  "+1 4 1 5..."    │
 Hang  Hang  Hang            └──► Redirect → Main Menu
```

## Requirements

- Python 3.8+
- Redis 6+
- PostgreSQL 13+
- Plivo account with a purchased phone number
