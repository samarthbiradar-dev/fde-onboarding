import json
import logging
import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from flask import Flask, jsonify, make_response, request
from plivo import plivoxml

# .env lives at project root, one level above this file
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

app = Flask(__name__)

BASE_URL    = os.getenv("BASE_URL", "").rstrip("/")
SESSION_TTL = 30 * 60


# ── Redis (optional — set REDIS_URL to enable session tracking) ───────────────

redis_client = None
try:
    import redis as redis_module
    _redis_url = os.getenv("REDIS_URL") or os.getenv("REDIS_HOST")
    if _redis_url:
        if _redis_url.startswith("redis://") or _redis_url.startswith("rediss://"):
            redis_client = redis_module.from_url(_redis_url, decode_responses=True)
        else:
            redis_client = redis_module.Redis(
                host=_redis_url,
                port=int(os.getenv("REDIS_PORT", 6379)),
                decode_responses=True,
            )
        redis_client.ping()
        log.info("Redis connected")
    else:
        log.warning("REDIS_URL not set — session tracking disabled")
except Exception as e:
    log.warning("Redis unavailable: %s", e)
    redis_client = None


# ── PostgreSQL (optional — set DATABASE_URL to enable call logging) ───────────

db      = None
CallLog = None

_db_url = os.getenv("DATABASE_URL", "")
if _db_url:
    try:
        from flask_sqlalchemy import SQLAlchemy
        from sqlalchemy import text as sa_text

        app.config["SQLALCHEMY_DATABASE_URI"]        = _db_url
        app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        db = SQLAlchemy(app)

        class CallLog(db.Model):  # noqa: F811
            __tablename__ = "call_logs"

            id          = db.Column(db.Integer, primary_key=True)
            call_uuid   = db.Column(db.String(64), unique=True, nullable=False)
            from_number = db.Column(db.String(30), nullable=False)
            to_number   = db.Column(db.String(30))
            duration    = db.Column(db.Integer)
            call_status = db.Column(db.String(30))
            menu_choice = db.Column(db.String(20))
            created_at  = db.Column(
                db.DateTime, default=lambda: datetime.now(timezone.utc)
            )

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

        log.info("PostgreSQL configured")
    except Exception as e:
        log.warning("PostgreSQL setup failed: %s", e)
        db      = None
        CallLog = None
else:
    log.warning("DATABASE_URL not set — call logging disabled")


# ── Helpers ───────────────────────────────────────────────────────────────────

def session_key(call_uuid: str) -> str:
    return f"ivr_session:{call_uuid}"


def xml_response(element, status: int = 200):
    resp = make_response(element.to_string(pretty=True), status)
    resp.headers["Content-Type"] = "text/xml"
    return resp


def error_hangup(message: str = "We're sorry, an error occurred. Goodbye."):
    r = plivoxml.ResponseElement()
    r.add(plivoxml.SpeakElement(message, voice="WOMAN", language="en-US"))
    r.add(plivoxml.HangupElement())
    return xml_response(r)


def build_main_menu() -> plivoxml.ResponseElement:
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
    response.add(plivoxml.SpeakElement(
        "We did not receive your selection. Let's try again.",
        voice="WOMAN",
        language="en-US",
    ))
    response.add(plivoxml.RedirectElement(
        f"{BASE_URL}/api/voice/inbound", method="POST"
    ))
    return response


# ── Utility routes ────────────────────────────────────────────────────────────

@app.route("/api/health", methods=["GET"])
def health():
    redis_ok = False
    db_ok    = False

    if redis_client:
        try:
            redis_client.ping()
            redis_ok = True
        except Exception:
            pass

    if db:
        try:
            db.session.execute(sa_text("SELECT 1"))
            db_ok = True
        except Exception:
            pass

    status = "OK"
    if (os.getenv("REDIS_URL") or os.getenv("REDIS_HOST")) and not redis_ok:
        status = "DEGRADED"
    if os.getenv("DATABASE_URL") and not db_ok:
        status = "DEGRADED"

    return jsonify({
        "status":   status,
        "redis":    "connected" if redis_ok else ("not configured" if not (os.getenv("REDIS_URL") or os.getenv("REDIS_HOST")) else "disconnected"),
        "postgres": "connected" if db_ok else ("not configured" if not os.getenv("DATABASE_URL") else "disconnected"),
        "base_url": BASE_URL or "(not set)",
    }), 200 if status == "OK" else 503


@app.route("/api/webhook-test", methods=["POST"])
def webhook_test():
    content_type = request.content_type or ""

    if "application/json" in content_type:
        body = request.get_json(silent=True) or {}
    elif "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
        body = request.form.to_dict()
    else:
        body = request.get_data(as_text=True) or "(empty)"

    log.debug("Webhook received | headers=%s body=%s", dict(request.headers), body)

    return jsonify({
        "received":     True,
        "method":       request.method,
        "content_type": content_type,
        "headers":      dict(request.headers),
        "body":         body,
    }), 200


# ── IVR routes ────────────────────────────────────────────────────────────────

@app.route("/api/voice/inbound", methods=["POST"])
def inbound():
    try:
        data        = request.form
        call_uuid   = data.get("CallUUID", "unknown")
        from_number = data.get("From", "unknown")
        to_number   = data.get("To", "unknown")

        log.info("Inbound call | UUID=%s From=%s To=%s", call_uuid, from_number, to_number)
        log.debug("Plivo payload: %s", dict(data))

        if redis_client:
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
            log.debug("Redis session created | key=%s", session_key(call_uuid))

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

        log.info("Menu selection | UUID=%s Digit=%r From=%s", call_uuid, digit, from_number)

        if redis_client:
            key = session_key(call_uuid)
            raw = redis_client.get(key)
            if raw:
                sess                = json.loads(raw)
                sess["menu_depth"]  = sess.get("menu_depth", 0) + 1
                sess["menu_choice"] = digit if digit else "timeout"
                redis_client.setex(key, SESSION_TTL, json.dumps(sess))

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
                "Invalid selection. Let's try again.",
                voice="WOMAN", language="en-US",
            ))
            response.add(plivoxml.RedirectElement(
                f"{BASE_URL}/api/voice/inbound", method="POST"
            ))

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
        duration    = data.get("Duration", "")
        call_status = data.get("CallStatus", "unknown")

        log.info("Call ended | UUID=%s Status=%s Duration=%ss", call_uuid, call_status, duration)

        menu_choice = None
        if redis_client:
            raw = redis_client.get(session_key(call_uuid))
            if raw:
                menu_choice = json.loads(raw).get("menu_choice")
                redis_client.delete(session_key(call_uuid))

        if db and CallLog:
            existing = CallLog.query.filter_by(call_uuid=call_uuid).first()
            if existing:
                log.warning("Duplicate hangup for UUID=%s — skipping", call_uuid)
                return jsonify({"status": "ok", "note": "duplicate"}), 200

            entry = CallLog(
                call_uuid   = call_uuid,
                from_number = from_number,
                to_number   = to_number,
                duration    = int(duration) if duration.isdigit() else None,
                call_status = call_status,
                menu_choice = menu_choice,
            )
            db.session.add(entry)
            db.session.commit()
            log.info("CallLog saved | id=%d", entry.id)
        else:
            log.warning("PostgreSQL not configured — call not logged to DB")

        return jsonify({"status": "ok"}), 200

    except Exception:
        log.exception("Error in /api/voice/call-ended")
        if db:
            db.session.rollback()
        return jsonify({"status": "error"}), 200


_MENU_LABELS = {
    "1": "Sales", "2": "Support", "3": "Number Readback",
    "timeout": "Timeout", None: "—",
}


@app.route("/call-history", methods=["GET"])
def call_history():
    if not db or not CallLog:
        return jsonify({"error": "PostgreSQL not configured"}), 503

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
  <meta charset="utf-8"><title>IVR Call History</title>
  <style>
    body{{font-family:sans-serif;padding:24px;color:#222}}
    h1{{margin-bottom:4px}}p{{margin-top:4px;color:#666}}
    table{{border-collapse:collapse;width:100%;margin-top:16px}}
    th,td{{border:1px solid #ddd;padding:8px 12px;text-align:left}}
    th{{background:#f4f4f4;font-weight:600}}
    tr:nth-child(even){{background:#fafafa}}a{{color:#0070f3}}
  </style>
</head>
<body>
  <h1>IVR Call History</h1>
  <p>{len(logs)} record(s) &nbsp;|&nbsp; <a href="/call-history?format=json">JSON</a></p>
  <table>
    <thead><tr>
      <th>ID</th><th>Call UUID</th><th>From</th><th>To</th>
      <th>Duration</th><th>Status</th><th>Menu Choice</th><th>Timestamp (UTC)</th>
    </tr></thead>
    <tbody>{rows or '<tr><td colspan="8" style="text-align:center;color:#999">No calls yet</td></tr>'}</tbody>
  </table>
</body></html>"""
        return html, 200, {"Content-Type": "text/html; charset=utf-8"}

    except Exception:
        log.exception("Error in /call-history")
        return jsonify({"error": "Failed to fetch history"}), 500


# Local development only — Vercel does not use this
if __name__ == "__main__":
    app.run(port=int(os.getenv("PORT", 5003)), debug=True)
