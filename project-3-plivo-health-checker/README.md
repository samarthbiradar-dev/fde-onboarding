# Project 3 — Plivo Health Checker

A CLI tool that connects to the Plivo API and prints a formatted health report showing account balance and the last 10 messages sent.

## Setup

**1. Install dependencies**
```bash
pip install -r requirements.txt
```

**2. Create your `.env` file**
```bash
cp .env.example .env
```

Edit `.env` and fill in your credentials from [Plivo Console](https://console.plivo.com):
```
PLIVO_AUTH_ID=your_auth_id_here
PLIVO_AUTH_TOKEN=your_auth_token_here
```

**3. Run**
```bash
python3 plivo_health_checker.py
```

## Sample Output

```
┌────────────────────────────────────────────────────────────────┐
│                  PLIVO ACCOUNT HEALTH REPORT                   │
├────────────────────────────────────────────────────────────────┤
│  Status                                               ✓  OK    │
│  Balance                                      $12.3400 USD     │
│  Account Name                                  My Company      │
│  Auth ID                                     MAXXXXXXXXXX      │
├────────────────────────────────────────────────────────────────┤
│                       LAST 10 MESSAGES                         │
├────────────────────────────────────────────────────────────────┤
│  Timestamp                To              Status               │
│  ──────────────────────── ─────────────── ────────────────     │
│  17 Jun 2026  10:23 UTC   +14151234567    ✓ delivered          │
│  16 Jun 2026  08:10 UTC   +919876543210   → sent               │
└────────────────────────────────────────────────────────────────┘
```

## Error Handling

| Scenario | Message |
|----------|---------|
| `.env` file missing | `Error: .env file not found` |
| API unreachable | `Error: Cannot connect to Plivo` |
| Wrong credentials | `Error: Invalid Plivo credentials` |
| Missing env vars | `Error: PLIVO_AUTH_ID and PLIVO_AUTH_TOKEN must be set in .env` |

## Requirements

- Python 3.7+
- Plivo account — [Sign up free](https://console.plivo.com/accounts/register/)
