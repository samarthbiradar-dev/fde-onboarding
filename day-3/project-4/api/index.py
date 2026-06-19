import json
import logging
import os
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from flask import Flask, jsonify, make_response, request
from plivo import plivoxml
from upstash_redis import Redis

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env.local"))
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

app = Flask(__name__)

SESSION_TTL   = 30 * 60
PLIVO_AUTH_ID = os.getenv("PLIVO_AUTH_ID", "")
PLIVO_AUTH_TOKEN = os.getenv("PLIVO_AUTH_TOKEN", "")

# ── Upstash Redis ─────────────────────────────────────────────────────────────
redis = Redis(
    url=os.getenv("KV_REST_API_URL"),
    token=os.getenv("KV_REST_API_TOKEN"),
)

# ── Postgres helpers ──────────────────────────────────────────────────────────
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS call_logs (
    id          SERIAL PRIMARY KEY,
    call_uuid   VARCHAR(64)  UNIQUE NOT NULL,
    from_number VARCHAR(30)  NOT NULL,
    to_number   VARCHAR(30),
    duration    INTEGER      DEFAULT 0,
    call_status VARCHAR(30),
    menu_choice VARCHAR(20),
    created_at  TIMESTAMPTZ  DEFAULT NOW()
);
"""

def get_conn(pooling: bool = True):
    url = os.getenv("POSTGRES_URL_NON_POOLING" if not pooling else "POSTGRES_URL")
    if not url:
        raise RuntimeError("POSTGRES_URL not set")
    return psycopg2.connect(
        url.replace("postgres://", "postgresql://", 1),
        cursor_factory=psycopg2.extras.RealDictCursor,
    )


# ── URL builder ───────────────────────────────────────────────────────────────
def base_url() -> str:
    """Build the deployment base URL from the current request."""
    return request.url_root.rstrip("/")


# ── XML helpers ───────────────────────────────────────────────────────────────
def xml_response(element, status: int = 200):
    resp = make_response(element.to_string(pretty=True), status)
    resp.headers["Content-Type"] = "text/xml"
    return resp


def error_hangup(msg: str = "We're sorry, an error occurred. Goodbye."):
    r = plivoxml.ResponseElement()
    r.add(plivoxml.SpeakElement(msg, voice="WOMAN", language="en-US"))
    r.add(plivoxml.HangupElement())
    return xml_response(r)


def build_main_menu() -> plivoxml.ResponseElement:
    b = base_url()
    response = plivoxml.ResponseElement()
    gd = plivoxml.GetDigitsElement(
        action=f"{b}/api/voice/menu-selection",
        method="POST",
        timeout=5,
        num_digits=1,
        retries=1,
    )
    gd.add(plivoxml.SpeakElement(
        "Welcome to Plivo. "
        "Press 1 for Sales. "
        "Press 2 for Technical Support. "
        "Press 3 to hear your phone number read back.",
        voice="WOMAN",
        language="en-US",
    ))
    response.add(gd)
    response.add(plivoxml.SpeakElement(
        "We did not receive your selection. Goodbye.",
        voice="WOMAN",
        language="en-US",
    ))
    response.add(plivoxml.HangupElement())
    return response


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/", methods=["GET"])
def index():
    b = base_url()
    return jsonify({
        "service": "IVR Phone System",
        "status":  "running",
        "plivo_configured": bool(PLIVO_AUTH_ID and PLIVO_AUTH_TOKEN),
        "webhook_urls": {
            "answer_url": f"{b}/api/voice/inbound",
            "hangup_url": f"{b}/api/voice/call-ended",
        },
        "endpoints": {
            "GET  /api/health":                "Service health check",
            "POST /api/setup-db":              "Create call_logs table",
            "POST /api/voice/inbound":         "Answer URL — Plivo calls this on inbound",
            "POST /api/voice/menu-selection":  "Digit handler (internal, called by Plivo XML)",
            "POST /api/voice/call-ended":      "Hangup URL — Plivo calls this on hangup",
            "GET  /api/call-history":          "View all logged calls",
        },
    }), 200


@app.route("/api/health", methods=["GET"])
def health():
    redis_ok = postgres_ok = False

    try:
        redis.set("__health__", "ok", ex=10)
        redis_ok = redis.get("__health__") == "ok"
    except Exception as e:
        log.warning("Redis health failed: %s", e)

    try:
        conn = get_conn()
        cur  = conn.cursor()
        cur.execute("SELECT 1")
        cur.close()
        conn.close()
        postgres_ok = True
    except Exception as e:
        log.warning("Postgres health failed: %s", e)

    ok = redis_ok and postgres_ok
    return jsonify({
        "status":            "OK" if ok else "DEGRADED",
        "redis":             "connected" if redis_ok else "disconnected",
        "postgres":          "connected" if postgres_ok else "disconnected",
        "plivo_configured":  bool(PLIVO_AUTH_ID and PLIVO_AUTH_TOKEN),
    }), 200 if ok else 503


@app.route("/api/setup-db", methods=["POST"])
def setup_db():
    try:
        conn = get_conn(pooling=False)
        conn.autocommit = True
        cur  = conn.cursor()
        cur.execute(CREATE_TABLE_SQL)
        cur.close()
        conn.close()
        return jsonify({"status": "ok", "message": "call_logs table is ready"}), 200
    except Exception as e:
        log.exception("setup-db failed")
        return jsonify({"error": str(e)}), 500


# ── IVR webhook routes ────────────────────────────────────────────────────────

@app.route("/api/voice/inbound", methods=["POST"])
def inbound():
    try:
        data        = request.form
        call_uuid   = data.get("CallUUID", "unknown")
        from_number = data.get("From", "unknown")
        to_number   = data.get("To", "unknown")

        log.info("Inbound call | UUID=%s From=%s To=%s", call_uuid, from_number, to_number)

        session = {
            "call_uuid":   call_uuid,
            "from_number": from_number,
            "to_number":   to_number,
            "status":      "active",
            "started_at":  datetime.now(timezone.utc).isoformat(),
            "menu_depth":  0,
            "menu_choice": None,
        }
        redis.set(f"ivr_session:{call_uuid}", json.dumps(session), ex=SESSION_TTL)

        return xml_response(build_main_menu())
    except Exception:
        log.exception("Error in /api/voice/inbound")
        return error_hangup()


@app.route("/api/voice/menu-selection", methods=["POST"])
def menu_selection():
    try:
        data        = request.form
        call_uuid   = data.get("CallUUID", "unknown")
        digit       = data.get("Digits", "").strip()
        from_number = data.get("From", "unknown")

        log.info("Menu selection | UUID=%s Digit=%r", call_uuid, digit)

        raw = redis.get(f"ivr_session:{call_uuid}")
        if raw:
            sess = json.loads(raw) if isinstance(raw, str) else raw
            sess["menu_depth"]  = sess.get("menu_depth", 0) + 1
            sess["menu_choice"] = digit or "timeout"
            redis.set(f"ivr_session:{call_uuid}", json.dumps(sess), ex=SESSION_TTL)

        response = plivoxml.ResponseElement()

        if digit == "1":
            response.add(plivoxml.SpeakElement(
                "Connecting you to our Sales team. Please hold.",
                voice="WOMAN", language="en-US",
            ))
            response.add(plivoxml.HangupElement())

        elif digit == "2":
            response.add(plivoxml.SpeakElement(
                "Connecting you to Technical Support. Please hold.",
                voice="WOMAN", language="en-US",
            ))
            response.add(plivoxml.HangupElement())

        elif digit == "3":
            readable = ", ".join(c for c in from_number if c.isdigit())
            response.add(plivoxml.SpeakElement(
                f"Your phone number is {readable}.",
                voice="WOMAN", language="en-US",
            ))
            response.add(plivoxml.HangupElement())

        else:
            response.add(plivoxml.SpeakElement(
                "Invalid selection. Goodbye.",
                voice="WOMAN", language="en-US",
            ))
            response.add(plivoxml.HangupElement())

        return xml_response(response)
    except Exception:
        log.exception("Error in /api/voice/menu-selection")
        return error_hangup()


@app.route("/api/voice/call-ended", methods=["POST"])
def call_ended():
    try:
        data        = request.form
        call_uuid   = data.get("CallUUID", "unknown")
        from_number = data.get("From", "unknown")
        to_number   = data.get("To", "unknown")
        duration    = data.get("Duration", "0")
        call_status = data.get("CallStatus", "unknown")

        log.info("Call ended | UUID=%s Status=%s Duration=%ss", call_uuid, call_status, duration)

        menu_choice = None
        raw = redis.get(f"ivr_session:{call_uuid}")
        if raw:
            sess        = json.loads(raw) if isinstance(raw, str) else raw
            menu_choice = sess.get("menu_choice")
            redis.delete(f"ivr_session:{call_uuid}")

        conn = get_conn()
        cur  = conn.cursor()
        cur.execute(
            """
            INSERT INTO call_logs (call_uuid, from_number, to_number, duration, call_status, menu_choice)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (call_uuid) DO NOTHING
            """,
            (call_uuid, from_number, to_number,
             int(duration) if duration.isdigit() else 0,
             call_status, menu_choice),
        )
        conn.commit()
        cur.close()
        conn.close()

        log.info("Call logged | uuid=%s choice=%s", call_uuid, menu_choice)
        return jsonify({"status": "ok"}), 200

    except Exception:
        log.exception("Error in /api/voice/call-ended")
        return jsonify({"status": "error"}), 200  # always 200 so Plivo doesn't retry


@app.route("/api/call-history", methods=["GET"])
def call_history():
    try:
        fmt  = request.args.get("format", "html")
        conn = get_conn()
        cur  = conn.cursor()
        cur.execute("SELECT * FROM call_logs ORDER BY created_at DESC")
        rows = cur.fetchall()
        cur.close()
        conn.close()

        logs = []
        for row in rows:
            entry = dict(row)
            if isinstance(entry.get("created_at"), datetime):
                entry["created_at"] = entry["created_at"].isoformat()
            logs.append(entry)

        if fmt == "json":
            return jsonify({"count": len(logs), "calls": logs}), 200

        _labels = {"1": "Sales", "2": "Support", "3": "Number Readback",
                   "timeout": "Timeout", None: "—"}
        rows_html = "".join(
            f"<tr>"
            f"<td>{l['id']}</td>"
            f"<td style='font-size:0.8em'>{l['call_uuid']}</td>"
            f"<td>{l['from_number']}</td>"
            f"<td>{l['to_number'] or '—'}</td>"
            f"<td>{l['duration']}s</td>"
            f"<td>{l['call_status'] or '—'}</td>"
            f"<td>{_labels.get(l['menu_choice'], l['menu_choice'])}</td>"
            f"<td>{l['created_at']}</td>"
            f"</tr>"
            for l in logs
        )
        html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>IVR Call History</title>
<style>body{{font-family:sans-serif;padding:24px}}table{{border-collapse:collapse;width:100%}}
th,td{{border:1px solid #ddd;padding:8px 12px;text-align:left}}
th{{background:#f4f4f4}}tr:nth-child(even){{background:#fafafa}}a{{color:#0070f3}}</style>
</head><body>
<h1>IVR Call History</h1>
<p>{len(logs)} record(s) &nbsp;|&nbsp; <a href="/api/call-history?format=json">JSON</a></p>
<table><thead><tr>
<th>ID</th><th>Call UUID</th><th>From</th><th>To</th>
<th>Duration</th><th>Status</th><th>Menu Choice</th><th>Timestamp</th>
</tr></thead><tbody>
{rows_html or '<tr><td colspan="8" style="text-align:center;color:#999">No calls yet</td></tr>'}
</tbody></table></body></html>"""
        return html, 200, {"Content-Type": "text/html; charset=utf-8"}

    except Exception:
        log.exception("Error in /api/call-history")
        return jsonify({"error": "Failed to fetch history"}), 500


if __name__ == "__main__":
    app.run(port=int(os.getenv("PORT", 5006)), debug=True)
