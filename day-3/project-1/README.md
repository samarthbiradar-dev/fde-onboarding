# Day 3 — Project 1: Flask IVR on Vercel (Serverless)

The Day 2 IVR app restructured to run as a Vercel serverless function.
All routes live under `/api`. Redis and PostgreSQL are optional — the
core IVR and webhook endpoints work without them.

## How it differs from Day 2 Project 4

| | Day 2 Project 4 | Day 3 Project 1 |
|---|---|---|
| Runtime | Local Flask (`python3 app.py`) | Vercel serverless |
| Entry point | `app.py` | `api/index.py` |
| Redis | Required at startup | Optional (graceful skip) |
| PostgreSQL | Required at startup | Optional (graceful skip) |
| Redis URL format | `REDIS_HOST` | `REDIS_URL` (supports `rediss://`) |
| BASE_URL | ngrok | Your Vercel deployment URL |

## Project structure

```
project-1/
├── api/
│   └── index.py      # Flask app — all routes
├── vercel.json       # Routes every request to api/index.py
├── requirements.txt  # Python dependencies
├── .env.example      # Environment variable template
└── README.md
```

## Endpoints

| Method | Path | Always works? | Description |
|--------|------|:---:|-------------|
| GET | `/api/health` | ✓ | Redis + PostgreSQL status |
| POST | `/api/webhook-test` | ✓ | Echo request headers and body |
| POST | `/api/voice/inbound` | ✓ | Plivo Answer URL — IVR menu XML |
| POST | `/api/voice/menu-selection` | ✓ | Digit routing (1/2/3/invalid) |
| POST | `/api/voice/call-ended` | needs DB | Logs call to PostgreSQL |
| GET | `/call-history` | needs DB | HTML call history dashboard |

## Setup & Deploy

### 1. Install the Vercel CLI

```bash
npm install -g vercel
```

Verify:
```bash
vercel --version
```

### 2. Log in to Vercel

```bash
vercel login
```

Choose your login method (GitHub recommended). Your browser will open to complete auth.

### 3. Create your local .env

```bash
cp .env.example .env
# BASE_URL will be filled in after your first deploy (step 5)
```

### 4. Deploy

From inside this directory:

```bash
cd day-3/project-1
vercel
```

First-time prompts:
- **Set up and deploy?** → `Y`
- **Which scope?** → your personal account
- **Link to existing project?** → `N`
- **Project name?** → `fde-ivr` (or anything)
- **Directory with source code?** → `.` (current directory)
- **Override settings?** → `N`

Vercel will deploy and print a URL like:
```
https://fde-ivr-abc123.vercel.app
```

### 5. Set BASE_URL and redeploy

Update your `.env`:
```
BASE_URL=https://fde-ivr-abc123.vercel.app
```

Then set it in Vercel (so it's available to the serverless function):
```bash
vercel env add BASE_URL
# Paste your deployment URL when prompted
# Select: Production, Preview, Development
```

Redeploy to apply:
```bash
vercel --prod
```

### 6. (Optional) Add Redis and PostgreSQL

For session tracking and call logging, add environment variables in the Vercel dashboard or via CLI:

```bash
# Upstash Redis (free tier at upstash.com)
vercel env add REDIS_URL

# Neon / Supabase PostgreSQL
vercel env add DATABASE_URL
```

Then redeploy: `vercel --prod`

---

## Verify the deployment

```bash
# Health check
curl https://your-project.vercel.app/api/health

# Webhook test
curl -X POST https://your-project.vercel.app/api/webhook-test \
  -H "Content-Type: application/json" \
  -d '{"event": "test", "source": "curl"}'

# Simulate Plivo inbound call
curl -X POST https://your-project.vercel.app/api/voice/inbound \
  -d "CallUUID=test-001&From=%2B14151234567&To=%2B18005550100"
```

## Local development with Vercel CLI

Run the app locally through the Vercel dev server (mirrors the serverless environment):

```bash
vercel dev
# Starts at http://localhost:3000
```

Or run Flask directly (faster for iteration):

```bash
pip install -r requirements.txt
python3 api/index.py
# Starts at http://localhost:5003
```

## Plivo configuration (after deploying)

In [console.plivo.com](https://console.plivo.com):
- **Answer URL**: `https://your-project.vercel.app/api/voice/inbound` — POST
- **Hangup URL**: `https://your-project.vercel.app/api/voice/call-ended` — POST
