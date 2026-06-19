import json
import logging
import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from flask import Flask, jsonify, request
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

SESSION_TTL = 30 * 60  # 30 minutes

# ── Upstash Redis ─────────────────────────────────────────────────────────────
# Reads KV_REST_API_URL and KV_REST_API_TOKEN from environment.
# These are auto-provisioned by the Vercel + Upstash integration.

redis = Redis(
    url=os.getenv("KV_REST_API_URL"),
    token=os.getenv("KV_REST_API_TOKEN"),
)


def session_key(call_uuid: str) -> str:
    return f"ivr_session:{call_uuid}"


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "service": "IVR Call Session API",
        "status":  "running",
        "endpoints": {
            "GET  /api/health":                "Redis connectivity check",
            "POST /api/sessions/start":        "Create a session (30-min TTL)",
            "GET  /api/sessions/{call_uuid}":  "Get session + remaining TTL",
            "PUT  /api/sessions/{call_uuid}":  "Update menu choice / depth",
            "DELETE /api/sessions/{call_uuid}":"End a session",
            "GET  /api/sessions":              "List all active sessions",
        },
    }), 200


@app.route("/api/health", methods=["GET"])
def health():
    try:
        redis.set("__health_check__", "ok", ex=10)
        redis_ok = redis.get("__health_check__") == "ok"
    except Exception as e:
        log.warning("Redis health check failed: %s", e)
        redis_ok = False

    return jsonify({
        "status":    "OK" if redis_ok else "DEGRADED",
        "redis":     "connected" if redis_ok else "disconnected",
        "provider":  "Upstash (KV_REST_API_URL)",
    }), 200 if redis_ok else 503


@app.route("/api/sessions/start", methods=["POST"])
def start_session():
    """
    Create a new call session in Redis.
    Body (JSON): { call_uuid, from_number, to_number }
    """
    try:
        data = request.get_json(silent=True) or {}

        call_uuid   = data.get("call_uuid")
        from_number = data.get("from_number")
        to_number   = data.get("to_number")

        if not call_uuid or not from_number:
            return jsonify({"error": "call_uuid and from_number are required"}), 400

        key = session_key(call_uuid)

        if redis.exists(key):
            return jsonify({"error": f"Session for '{call_uuid}' already exists"}), 409

        session = {
            "call_uuid":   call_uuid,
            "from_number": from_number,
            "to_number":   to_number or "",
            "status":      "active",
            "menu_depth":  0,
            "menu_choice": None,
            "started_at":  datetime.now(timezone.utc).isoformat(),
        }

        redis.set(key, json.dumps(session), ex=SESSION_TTL)
        ttl = redis.ttl(key)

        log.info("Session started | uuid=%s from=%s", call_uuid, from_number)
        return jsonify({"status": "created", "session": session, "ttl_seconds": ttl}), 201

    except Exception:
        log.exception("Error in /api/sessions/start")
        return jsonify({"error": "internal server error"}), 500


@app.route("/api/sessions/<call_uuid>", methods=["GET"])
def get_session(call_uuid):
    """Retrieve an active session and its remaining TTL."""
    try:
        raw = redis.get(session_key(call_uuid))
        if not raw:
            return jsonify({"error": f"No active session for '{call_uuid}'"}), 404

        session = json.loads(raw) if isinstance(raw, str) else raw
        ttl     = redis.ttl(session_key(call_uuid))

        return jsonify({"session": session, "ttl_seconds": ttl}), 200

    except Exception:
        log.exception("Error in GET /api/sessions/%s", call_uuid)
        return jsonify({"error": "internal server error"}), 500


@app.route("/api/sessions/<call_uuid>", methods=["PUT"])
def update_session(call_uuid):
    """
    Update menu_depth and/or menu_choice on an active session.
    Body (JSON): { menu_choice, menu_depth }  (both optional)
    Resets TTL to 30 minutes on every update.
    """
    try:
        raw = redis.get(session_key(call_uuid))
        if not raw:
            return jsonify({"error": f"No active session for '{call_uuid}'"}), 404

        session = json.loads(raw) if isinstance(raw, str) else raw
        updates = request.get_json(silent=True) or {}

        if "menu_choice" in updates:
            session["menu_choice"] = updates["menu_choice"]
        if "menu_depth" in updates:
            session["menu_depth"] = updates["menu_depth"]
        else:
            session["menu_depth"] = session.get("menu_depth", 0) + 1

        session["updated_at"] = datetime.now(timezone.utc).isoformat()

        redis.set(session_key(call_uuid), json.dumps(session), ex=SESSION_TTL)
        ttl = redis.ttl(session_key(call_uuid))

        log.info("Session updated | uuid=%s choice=%s depth=%s",
                 call_uuid, session["menu_choice"], session["menu_depth"])
        return jsonify({"status": "updated", "session": session, "ttl_seconds": ttl}), 200

    except Exception:
        log.exception("Error in PUT /api/sessions/%s", call_uuid)
        return jsonify({"error": "internal server error"}), 500


@app.route("/api/sessions/<call_uuid>", methods=["DELETE"])
def delete_session(call_uuid):
    """End a session — removes it from Redis."""
    try:
        key     = session_key(call_uuid)
        raw     = redis.get(key)
        if not raw:
            return jsonify({"error": f"No active session for '{call_uuid}'"}), 404

        redis.delete(key)
        log.info("Session deleted | uuid=%s", call_uuid)
        return jsonify({"status": "deleted", "call_uuid": call_uuid}), 200

    except Exception:
        log.exception("Error in DELETE /api/sessions/%s", call_uuid)
        return jsonify({"error": "internal server error"}), 500


@app.route("/api/sessions", methods=["GET"])
def list_sessions():
    """List all active session keys in Redis."""
    try:
        keys    = redis.keys("ivr_session:*")
        results = []
        for key in keys:
            raw = redis.get(key)
            if raw:
                session = json.loads(raw) if isinstance(raw, str) else raw
                ttl     = redis.ttl(key)
                results.append({"session": session, "ttl_seconds": ttl})

        return jsonify({"count": len(results), "sessions": results}), 200

    except Exception:
        log.exception("Error in GET /api/sessions")
        return jsonify({"error": "internal server error"}), 500


if __name__ == "__main__":
    app.run(port=int(os.getenv("PORT", 5004)), debug=True)
