# Day 2 — Project 2: PostgreSQL Call Log

Flask API backed by PostgreSQL via SQLAlchemy. Stores and retrieves call logs with phone number, menu choice, and timestamp.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Returns `{"status": "OK"}` |
| POST | `/log-call` | Save a call log entry |
| GET | `/call-logs` | Return all call logs (newest first) |

## Setup

**1. Install PostgreSQL**
```bash
brew install postgresql@16
brew services start postgresql@16
```

**2. Create the database**
```bash
createdb calllog_db
```

**3. Install Python dependencies**
```bash
pip install -r requirements.txt
```

**4. Create the tables**
```bash
python3 create_db.py
```

**5. Run the server**
```bash
python3 app.py
```
Server starts at `http://localhost:5001`

## Testing

**Save a call:**
```bash
curl -X POST http://localhost:5001/log-call \
  -H "Content-Type: application/json" \
  -d '{"phone_number": "+14151234567", "menu_choice": "sales"}'
```

**Get all calls:**
```bash
curl http://localhost:5001/call-logs
```

## Model

| Field | Type | Notes |
|-------|------|-------|
| id | Integer | Auto-increment primary key |
| phone_number | String(20) | Required |
| menu_choice | String(100) | Required |
| timestamp | DateTime | Auto-set to UTC on insert |

## Requirements

- Python 3.8+
- PostgreSQL 14+
