# Day 2 — Project 3: Redis Call Session

Flask API that stores call session state in Redis with a 30-minute TTL. Sessions auto-expire — no cleanup needed.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check + Redis connection status |
| POST | `/start-call` | Create a session for a call (30-min TTL) |
| GET | `/session/<call_id>` | Get session data + remaining TTL |
| POST | `/end-call/<call_id>` | Manually end/delete a session |

## Setup

**1. Install and start Redis**
```bash
brew install redis
brew services start redis
redis-cli ping   # should return PONG
```

**2. Install Python dependencies**
```bash
pip install -r requirements.txt
```

**3. Run the server**
```bash
python3 app.py
```
Server starts at `http://localhost:5002`

## Testing

**Start a call session:**
```bash
curl -X POST http://localhost:5002/start-call \
  -H "Content-Type: application/json" \
  -d '{"call_id": "call_abc123", "phone_number": "+14151234567", "menu_choice": "sales"}'
```

**Check the session:**
```bash
curl http://localhost:5002/session/call_abc123
```

**End the session:**
```bash
curl -X POST http://localhost:5002/end-call/call_abc123
```

## Verifying with redis-cli

```bash
redis-cli

# List all call sessions
KEYS call_session:*

# Get raw session data
GET call_session:call_abc123

# Check TTL (seconds remaining)
TTL call_session:call_abc123

# Watch it expire in real time
DEBUG SLEEP 0   # wake up redis
TTL call_session:call_abc123
```

## How TTL works

- Every session is stored with `SETEX key 1800 value`
- Redis automatically deletes the key after 1800 seconds (30 min)
- `TTL` returns remaining seconds; `-2` means the key is gone

## Requirements

- Python 3.8+
- Redis 6+
