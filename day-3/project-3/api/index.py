import logging
import os
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from flask import Flask, jsonify, request

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env.local"))
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

app = Flask(__name__)


def get_conn(pooling: bool = True):
    """Return a new psycopg2 connection. Use pooling=False for DDL."""
    url = os.getenv("POSTGRES_URL_NON_POOLING" if not pooling else "POSTGRES_URL")
    if not url:
        raise RuntimeError("POSTGRES_URL env var not set")
    # psycopg2 needs postgresql:// not postgres://
    url = url.replace("postgres://", "postgresql://", 1)
    return psycopg2.connect(url, cursor_factory=psycopg2.extras.RealDictCursor)


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


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "service": "Call Log API",
        "status": "running",
        "endpoints": {
            "GET  /api/health":     "Postgres connectivity check",
            "POST /api/setup-db":   "Create call_logs table",
            "POST /api/log-call":   "Insert a call log entry",
            "GET  /api/call-logs":  "List all call logs (newest first)",
            "GET  /api/call-history": "Per-caller summary with last call",
        },
    }), 200


@app.route("/api/health", methods=["GET"])
def health():
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.close()
        conn.close()
        return jsonify({"status": "OK", "postgres": "connected"}), 200
    except Exception as e:
        log.warning("Health check failed: %s", e)
        return jsonify({"status": "DEGRADED", "postgres": "disconnected", "error": str(e)}), 503


@app.route("/api/setup-db", methods=["POST"])
def setup_db():
    """Create the call_logs table if it doesn't exist."""
    try:
        conn = get_conn(pooling=False)
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(CREATE_TABLE_SQL)
        cur.close()
        conn.close()
        log.info("call_logs table ensured")
        return jsonify({"status": "ok", "message": "call_logs table is ready"}), 200
    except Exception as e:
        log.exception("setup-db failed")
        return jsonify({"error": str(e)}), 500


@app.route("/api/log-call", methods=["POST"])
def log_call():
    """
    Insert a call log entry.
    Body (JSON): { call_uuid, from_number, to_number?, duration?, call_status?, menu_choice? }
    """
    try:
        data = request.get_json(silent=True) or {}

        call_uuid   = data.get("call_uuid")
        from_number = data.get("from_number")

        if not call_uuid or not from_number:
            return jsonify({"error": "call_uuid and from_number are required"}), 400

        conn = get_conn()
        cur  = conn.cursor()
        cur.execute(
            """
            INSERT INTO call_logs (call_uuid, from_number, to_number, duration, call_status, menu_choice)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (call_uuid) DO NOTHING
            RETURNING *
            """,
            (
                call_uuid,
                from_number,
                data.get("to_number"),
                data.get("duration", 0),
                data.get("call_status", "completed"),
                data.get("menu_choice"),
            ),
        )
        row = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        if row is None:
            return jsonify({"status": "duplicate", "message": f"call_uuid '{call_uuid}' already logged"}), 409

        entry = dict(row)
        if isinstance(entry.get("created_at"), datetime):
            entry["created_at"] = entry["created_at"].isoformat()

        log.info("Call logged | uuid=%s from=%s", call_uuid, from_number)
        return jsonify({"status": "logged", "call_log": entry}), 201

    except Exception as e:
        log.exception("log-call failed")
        return jsonify({"error": str(e)}), 500


@app.route("/api/call-logs", methods=["GET"])
def call_logs():
    """List all call logs, newest first. Supports ?limit=N&offset=N."""
    try:
        limit  = min(int(request.args.get("limit",  100)), 500)
        offset = int(request.args.get("offset", 0))

        conn = get_conn()
        cur  = conn.cursor()
        cur.execute(
            "SELECT * FROM call_logs ORDER BY created_at DESC LIMIT %s OFFSET %s",
            (limit, offset),
        )
        rows = cur.fetchall()

        cur.execute("SELECT COUNT(*) AS total FROM call_logs")
        total = cur.fetchone()["total"]

        cur.close()
        conn.close()

        logs = []
        for row in rows:
            entry = dict(row)
            if isinstance(entry.get("created_at"), datetime):
                entry["created_at"] = entry["created_at"].isoformat()
            logs.append(entry)

        return jsonify({"total": total, "count": len(logs), "call_logs": logs}), 200

    except Exception as e:
        log.exception("call-logs failed")
        return jsonify({"error": str(e)}), 500


@app.route("/api/call-history", methods=["GET"])
def call_history():
    """Per-caller summary: total calls, total duration, last call time, last menu choice."""
    try:
        conn = get_conn()
        cur  = conn.cursor()
        cur.execute(
            """
            SELECT
                from_number,
                COUNT(*)                          AS total_calls,
                COALESCE(SUM(duration), 0)        AS total_duration_seconds,
                MAX(created_at)                   AS last_call_at,
                (ARRAY_AGG(menu_choice ORDER BY created_at DESC))[1] AS last_menu_choice,
                (ARRAY_AGG(call_status  ORDER BY created_at DESC))[1] AS last_call_status
            FROM call_logs
            GROUP BY from_number
            ORDER BY last_call_at DESC
            """
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()

        history = []
        for row in rows:
            entry = dict(row)
            if isinstance(entry.get("last_call_at"), datetime):
                entry["last_call_at"] = entry["last_call_at"].isoformat()
            history.append(entry)

        return jsonify({"count": len(history), "call_history": history}), 200

    except Exception as e:
        log.exception("call-history failed")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(port=int(os.getenv("PORT", 5005)), debug=True)
