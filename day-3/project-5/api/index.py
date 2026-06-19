import logging
import os
import time
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from flask import Flask, jsonify
from upstash_redis import Redis

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env.local"))
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

app = Flask(__name__)

redis = Redis(
    url=os.getenv("KV_REST_API_URL"),
    token=os.getenv("KV_REST_API_TOKEN"),
)


def check_redis() -> dict:
    start = time.monotonic()
    try:
        redis.set("__health__", "ok", ex=30)
        val = redis.get("__health__")
        latency_ms = round((time.monotonic() - start) * 1000, 2)

        keys = redis.keys("ivr_session:*")
        active_sessions = len(keys) if keys else 0

        return {
            "status":          "ok",
            "latency_ms":      latency_ms,
            "ping":            val == "ok",
            "active_sessions": active_sessions,
            "provider":        "Upstash (KV_REST_API_URL)",
        }
    except Exception as e:
        latency_ms = round((time.monotonic() - start) * 1000, 2)
        log.warning("Redis check failed: %s", e)
        return {
            "status":     "error",
            "latency_ms": latency_ms,
            "error":      str(e),
        }


def check_postgres() -> dict:
    start = time.monotonic()
    url   = os.getenv("POSTGRES_URL", "").replace("postgres://", "postgresql://", 1)
    if not url:
        return {"status": "error", "error": "POSTGRES_URL not set"}
    try:
        conn = psycopg2.connect(url, cursor_factory=psycopg2.extras.RealDictCursor)
        cur  = conn.cursor()
        cur.execute("SELECT 1 AS ping")
        cur.fetchone()

        # Count rows in call_logs if the table exists
        call_log_count = None
        try:
            cur.execute("SELECT COUNT(*) AS n FROM call_logs")
            call_log_count = cur.fetchone()["n"]
        except Exception:
            pass

        latency_ms = round((time.monotonic() - start) * 1000, 2)
        cur.close()
        conn.close()

        result = {
            "status":     "ok",
            "latency_ms": latency_ms,
            "ping":       True,
            "provider":   "Neon (POSTGRES_URL)",
        }
        if call_log_count is not None:
            result["call_log_rows"] = call_log_count
        return result

    except Exception as e:
        latency_ms = round((time.monotonic() - start) * 1000, 2)
        log.warning("Postgres check failed: %s", e)
        return {
            "status":     "error",
            "latency_ms": latency_ms,
            "error":      str(e),
        }


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "service": "IVR Health Monitor",
        "endpoints": {
            "GET /api/health":          "Full health check (Redis + Postgres)",
            "GET /api/health/redis":    "Redis-only check",
            "GET /api/health/postgres": "Postgres-only check",
        },
    }), 200


@app.route("/api/health", methods=["GET"])
def health():
    checked_at = datetime.now(timezone.utc).isoformat()

    r_check = check_redis()
    p_check = check_postgres()

    all_ok  = r_check["status"] == "ok" and p_check["status"] == "ok"
    overall = "OK" if all_ok else "DEGRADED"

    http_status = 200 if all_ok else 503
    log.info("Health check | overall=%s redis=%s postgres=%s",
             overall, r_check["status"], p_check["status"])

    return jsonify({
        "status":     overall,
        "checked_at": checked_at,
        "services": {
            "redis":    r_check,
            "postgres": p_check,
        },
    }), http_status


@app.route("/api/health/redis", methods=["GET"])
def health_redis():
    result = check_redis()
    return jsonify(result), 200 if result["status"] == "ok" else 503


@app.route("/api/health/postgres", methods=["GET"])
def health_postgres():
    result = check_postgres()
    return jsonify(result), 200 if result["status"] == "ok" else 503


if __name__ == "__main__":
    app.run(port=int(os.getenv("PORT", 5007)), debug=True)
