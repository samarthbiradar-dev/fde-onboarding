import json
import os
from datetime import datetime, timezone

import redis
from dotenv import load_dotenv
from flask import Flask, request, jsonify

load_dotenv()

app = Flask(__name__)

SESSION_TTL = 30 * 60  # 30 minutes in seconds

try:
    r = redis.Redis(
        host=os.getenv("REDIS_HOST", "localhost"),
        port=int(os.getenv("REDIS_PORT", 6379)),
        db=0,
        decode_responses=True,
    )
    r.ping()
except redis.ConnectionError:
    raise RuntimeError("Cannot connect to Redis — is it running? (brew services start redis)")


def session_key(call_id):
    return f"call_session:{call_id}"


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "OK", "redis": "connected"}), 200


@app.route("/start-call", methods=["POST"])
def start_call():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Request body must be JSON"}), 400

    call_id      = data.get("call_id")
    phone_number = data.get("phone_number")
    menu_choice  = data.get("menu_choice")

    if not call_id or not phone_number:
        return jsonify({"error": "call_id and phone_number are required"}), 400

    session = {
        "call_id":      call_id,
        "phone_number": phone_number,
        "menu_choice":  menu_choice or "none",
        "status":       "active",
        "started_at":   datetime.now(timezone.utc).isoformat(),
    }

    r.setex(session_key(call_id), SESSION_TTL, json.dumps(session))

    ttl = r.ttl(session_key(call_id))
    return jsonify({"status": "session_started", "session": session, "expires_in_seconds": ttl}), 201


@app.route("/session/<call_id>", methods=["GET"])
def get_session(call_id):
    raw = r.get(session_key(call_id))
    if not raw:
        return jsonify({"error": f"No active session for call_id '{call_id}'"}), 404

    session = json.loads(raw)
    ttl     = r.ttl(session_key(call_id))
    return jsonify({"session": session, "expires_in_seconds": ttl}), 200


@app.route("/end-call/<call_id>", methods=["POST"])
def end_call(call_id):
    key = session_key(call_id)
    raw = r.get(key)
    if not raw:
        return jsonify({"error": f"No active session for call_id '{call_id}'"}), 404

    r.delete(key)
    return jsonify({"status": "session_ended", "call_id": call_id}), 200


if __name__ == "__main__":
    app.run(port=5002, debug=True)
