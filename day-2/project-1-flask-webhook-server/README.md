# Project 4 — Flask Webhook Server

A lightweight Flask server with a health check endpoint and a webhook receiver — exposable to the internet via ngrok.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Returns `{"status": "OK"}` |
| POST | `/webhook-test` | Prints incoming headers + body, returns `{"received": true}` |

## Setup

**1. Install dependencies**
```bash
pip install -r requirements.txt
```

**2. Run the server**
```bash
python3 app.py
```
Server starts at `http://localhost:5000`

**3. Test locally**
```bash
# Health check
curl http://localhost:5000/health

# Send a test webhook
curl -X POST http://localhost:5000/webhook-test \
  -H "Content-Type: application/json" \
  -d '{"event": "message.delivered", "id": "abc123"}'
```

## Expose with ngrok

**1. Install ngrok**
```bash
brew install ngrok/ngrok/ngrok
```

**2. Authenticate ngrok** (one-time, free account at ngrok.com)
```bash
ngrok config add-authtoken YOUR_TOKEN_HERE
```

**3. Expose your local server**
```bash
ngrok http 5000
```

ngrok gives you a public URL like:
```
Forwarding  https://abc123.ngrok-free.app -> http://localhost:5000
```

**4. Use your public webhook URL**
```
https://abc123.ngrok-free.app/webhook-test
```

Paste this URL into any service (Plivo, Stripe, GitHub, etc.) as the webhook destination.
Every incoming request will be printed live in your terminal.
