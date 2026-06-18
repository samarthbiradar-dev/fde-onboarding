import json
import logging
import os
from datetime import datetime, timezone

import redis as redis_module
from dotenv import load_dotenv
from flask import Flask, jsonify, make_response, request
from flask_sqlalchemy import SQLAlchemy
from plivo import plivoxml
from sqlalchemy import text

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
    "DATABASE_URL", "postgresql://localhost/ivr_db"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

BASE_URL    = os.getenv("BASE_URL", "http://localhost:5003").rstrip("/")
SESSION_TTL = 30 * 60  # 30 minutes in seconds

# ── Redis ─────────────────────────────────────────────────────────────────────

try:
    redis_client = redis_module.Redis(
        host=os.getenv("REDIS_HOST", "localhost"),
        port=int(os.getenv("REDIS_PORT", 6379)),
        db=0,
        decode_responses=True,
    )
    redis_client.ping()
    log.info("Redis connected successfully")
except redis_module.ConnectionError:
    raise RuntimeError("Cannot connect to Redis — is it running? (brew services start redis)")


# ── PostgreSQL Model ──────────────────────────────────────────────────────────

class CallLog(db.Model):
    __tablename__ = "call_logs"

    id          = db.Column(db.Integer, primary_key=True)
    call_uuid   = db.Column(db.String(64), unique=True, nullable=False)
    from_number = db.Column(db.String(30), nullable=False)
    to_number   = db.Column(db.String(30))
    duration    = db.Column(db.Integer)       # seconds
    call_status = db.Column(db.String(30))    # completed, failed, busy, etc.
    menu_choice = db.Column(db.String(20))    # digit pressed: "1", "2", "3", or "timeout"
    created_at  = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "id":          self.id,
            "call_uuid":   self.call_uuid,
            "from_number": self.from_number,
            "to_number":   self.to_number,
            "duration":    self.duration,
            "call_status": self.call_status,
            "menu_choice": self.menu_choice,
            "created_at":  self.created_at.isoformat(),
        }


# ── Helpers ───────────────────────────────────────────────────────────────────

def session_key(call_uuid: str) -> str:
    return f"ivr_session:{call_uuid}"


def xml_response(element, status: int = 200):
    """Wrap a plivoxml ResponseElement as a Flask response."""
    resp = make_response(element.to_string(pretty=True), status)
    resp.headers["Content-Type"] = "text/xml"
    return resp


def error_hangup(message: str = "We're sorry, an error occurred. Goodbye."):
    """Minimal safe XML response: speak an error and hang up."""
    r = plivoxml.ResponseElement()
    r.add(plivoxml.SpeakElement(message, voice="WOMAN", language="en-US"))
    r.add(plivoxml.HangupElement())
    return xml_response(r)


def build_main_menu() -> plivoxml.ResponseElement:
    """Return the root IVR menu as a Plivo ResponseElement."""
    response = plivoxml.ResponseElement()

    gd = plivoxml.GetDigitsElement(
        action=f"{BASE_URL}/api/voice/menu-selection",
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

    # Reached only when GetDigits times out with no input from the caller
    response.add(plivoxml.SpeakElement(
        "We did not receive your selection. Let's try again.",
        voice="WOMAN",
        language="en-US",
    ))
    response.add(plivoxml.RedirectElement(
        f"{BASE_URL}/api/voice/inbound", method="POST"
    ))

    return response


# ── IVR Routes ────────────────────────────────────────────────────────────────

@app.route("/api/voice/inbound", methods=["POST"])
def inbound():
    """
    Plivo Answer URL — called when an inbound call arrives.
    Initialises a Redis session and returns the main IVR menu XML.
    """
    try:
        data        = request.form
        call_uuid   = data.get("CallUUID", "unknown")
        from_number = data.get("From", "unknown")
        to_number   = data.get("To", "unknown")

        log.info("Inbound call | UUID=%s From=%s To=%s", call_uuid, from_number, to_number)
        log.debug("Full Plivo payload: %s", dict(data))

        session = {
            "call_uuid":   call_uuid,
            "from":        from_number,
            "to":          to_number,
            "status":      "active",
            "started_at":  datetime.now(timezone.utc).isoformat(),
            "menu_depth":  0,
            "menu_choice": None,
        }
        redis_client.setex(session_key(call_uuid), SESSION_TTL, json.dumps(session))
        log.debug("Redis session created | key=%s ttl=%ds", session_key(call_uuid), SESSION_TTL)

        return xml_response(build_main_menu())

    except Exception:
        log.exception("Unhandled error in /api/voice/inbound")
        return error_hangup()


@app.route("/api/voice/menu-selection", methods=["POST"])
def menu_selection():
    """
    Plivo action URL for GetDigits.
    Routes the caller based on the digit they pressed and updates Redis state.
    """
    try:
        data        = request.form
        call_uuid   = data.get("CallUUID", "unknown")
        digit       = data.get("Digits", "").strip()
        from_number = data.get("From", "unknown")

        log.info("Menu selection | UUID=%s Digit=%r From=%s", call_uuid, digit, from_number)
        log.debug("Full Plivo payload: %s", dict(data))

        # Update Redis session with the current menu depth and choice
        key = session_key(call_uuid)
        raw = redis_client.get(key)
        if raw:
            sess                = json.loads(raw)
            sess["menu_depth"]  = sess.get("menu_depth", 0) + 1
            sess["menu_choice"] = digit if digit else "timeout"
            redis_client.setex(key, SESSION_TTL, json.dumps(sess))
            log.debug("Redis session updated | key=%s depth=%d choice=%s",
                      key, sess["menu_depth"], sess["menu_choice"])
        else:
            log.warning("No Redis session found for UUID=%s (call may have expired)", call_uuid)

        response = plivoxml.ResponseElement()

        if digit == "1":
            log.info("Option 1 — Sales | UUID=%s", call_uuid)
            response.add(plivoxml.SpeakElement(
                "Connecting you to our Sales team. Please hold.",
                voice="WOMAN", language="en-US",
            ))
            response.add(plivoxml.HangupElement())

        elif digit == "2":
            log.info("Option 2 — Technical Support | UUID=%s", call_uuid)
            response.add(plivoxml.SpeakElement(
                "Connecting you to Technical Support. Please hold.",
                voice="WOMAN", language="en-US",
            ))
            response.add(plivoxml.HangupElement())

        elif digit == "3":
            # Separate every digit with a comma so TTS reads each one individually
            readable = ", ".join(c for c in from_number if c.isdigit())
            log.info("Option 3 — Number readback %s | UUID=%s", from_number, call_uuid)
            response.add(plivoxml.SpeakElement(
                f"Your phone number is {readable}.",
                voice="WOMAN", language="en-US",
            ))
            response.add(plivoxml.HangupElement())

        else:
            log.info("Invalid/empty digit %r — looping menu | UUID=%s", digit, call_uuid)
            response.add(plivoxml.SpeakElement(
                "Invalid selection. Let's try again.",
                voice="WOMAN", language="en-US",
            ))
            response.add(plivoxml.RedirectElement(
                f"{BASE_URL}/api/voice/inbound", method="POST"
            ))

        return xml_response(response)

    except Exception:
        log.exception("Unhandled error in /api/voice/menu-selection")
        return error_hangup()


@app.route("/api/voice/call-ended", methods=["POST"])
def call_ended():
    """
    Plivo Hangup URL — called when a call ends.
    Reads final menu choice from Redis, persists a CallLog row to PostgreSQL,
    then cleans up the Redis session.
    """
    try:
        data        = request.form
        call_uuid   = data.get("CallUUID", "unknown")
        from_number = data.get("From", "unknown")
        to_number   = data.get("To", "unknown")
        duration    = data.get("Duration", "")
        call_status = data.get("CallStatus", "unknown")

        log.info("Call ended | UUID=%s Status=%s Duration=%ss",
                 call_uuid, call_status, duration)
        log.debug("Full Plivo hangup payload: %s", dict(data))

        # Guard against duplicate hangup webhooks from Plivo
        existing = CallLog.query.filter_by(call_uuid=call_uuid).first()
        if existing:
            log.warning("Duplicate hangup webhook for UUID=%s — skipping DB write", call_uuid)
            return jsonify({"status": "ok", "note": "duplicate"}), 200

        # Pull menu_choice out of Redis before deleting the session
        raw         = redis_client.get(session_key(call_uuid))
        menu_choice = None
        if raw:
            sess        = json.loads(raw)
            menu_choice = sess.get("menu_choice")
            redis_client.delete(session_key(call_uuid))
            log.debug("Redis session deleted | key=%s", session_key(call_uuid))
        else:
            log.warning("No Redis session for UUID=%s at hangup", call_uuid)

        log_entry = CallLog(
            call_uuid   = call_uuid,
            from_number = from_number,
            to_number   = to_number,
            duration    = int(duration) if duration.isdigit() else None,
            call_status = call_status,
            menu_choice = menu_choice,
        )
        db.session.add(log_entry)
        db.session.commit()
        log.info("CallLog persisted | id=%d UUID=%s menu_choice=%s",
                 log_entry.id, call_uuid, menu_choice)

        return jsonify({"status": "ok"}), 200

    except Exception:
        log.exception("Unhandled error in /api/voice/call-ended")
        db.session.rollback()
        # Return 200 so Plivo does not keep retrying this webhook
        return jsonify({"status": "error", "detail": "internal error — see server logs"}), 200


# ── Dashboard & Utility Routes ────────────────────────────────────────────────

_MENU_LABELS = {"1": "Sales", "2": "Support", "3": "Number Readback",
                "timeout": "Timeout", None: "—"}


@app.route("/call-history", methods=["GET"])
def call_history():
    """
    Call history dashboard.
    Default: HTML table.  Add ?format=json for a JSON array.
    """
    try:
        fmt  = request.args.get("format", "html")
        logs = CallLog.query.order_by(CallLog.created_at.desc()).all()

        if fmt == "json":
            return jsonify({"count": len(logs), "calls": [l.to_dict() for l in logs]}), 200

        rows = "".join(
            f"<tr>"
            f"<td>{l.id}</td>"
            f"<td style='font-size:0.8em'>{l.call_uuid}</td>"
            f"<td>{l.from_number}</td>"
            f"<td>{l.to_number or '—'}</td>"
            f"<td>{l.duration if l.duration is not None else '—'}s</td>"
            f"<td>{l.call_status or '—'}</td>"
            f"<td>{_MENU_LABELS.get(l.menu_choice, l.menu_choice)}</td>"
            f"<td>{l.created_at.strftime('%Y-%m-%d %H:%M:%S')} UTC</td>"
            f"</tr>"
            for l in logs
        )

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>IVR Call History</title>
  <style>
    body  {{ font-family: sans-serif; padding: 24px; color: #222; }}
    h1    {{ margin-bottom: 4px; }}
    p     {{ margin-top: 4px; color: #666; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 16px; }}
    th, td{{ border: 1px solid #ddd; padding: 8px 12px; text-align: left; }}
    th    {{ background: #f4f4f4; font-weight: 600; }}
    tr:nth-child(even) {{ background: #fafafa; }}
    a     {{ color: #0070f3; }}
  </style>
</head>
<body>
  <h1>IVR Call History</h1>
  <p>{len(logs)} record(s) &nbsp;|&nbsp; <a href="/call-history?format=json">View as JSON</a></p>
  <table>
    <thead>
      <tr>
        <th>ID</th>
        <th>Call UUID</th>
        <th>From</th>
        <th>To</th>
        <th>Duration</th>
        <th>Status</th>
        <th>Menu Choice</th>
        <th>Timestamp (UTC)</th>
      </tr>
    </thead>
    <tbody>{rows if rows else '<tr><td colspan="8" style="text-align:center;color:#999">No calls yet</td></tr>'}</tbody>
  </table>
</body>
</html>"""

        return html, 200, {"Content-Type": "text/html; charset=utf-8"}

    except Exception:
        log.exception("Error in /call-history")
        return jsonify({"error": "Failed to fetch call history"}), 500


@app.route("/health", methods=["GET"])
def health():
    redis_ok = False
    db_ok    = False

    try:
        redis_client.ping()
        redis_ok = True
    except Exception:
        log.warning("Redis health check failed")

    try:
        db.session.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        log.warning("PostgreSQL health check failed")

    status = "OK" if (redis_ok and db_ok) else "DEGRADED"
    return jsonify({
        "status":   status,
        "redis":    "connected" if redis_ok else "disconnected",
        "postgres": "connected" if db_ok else "disconnected",
        "base_url": BASE_URL,
    }), 200 if status == "OK" else 503


if __name__ == "__main__":
    app.run(port=5003, debug=True)
