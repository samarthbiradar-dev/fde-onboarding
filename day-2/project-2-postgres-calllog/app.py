import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy

load_dotenv()

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
    "DATABASE_URL", "postgresql://localhost/calllog_db"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


class CallLog(db.Model):
    __tablename__ = "call_logs"

    id           = db.Column(db.Integer, primary_key=True)
    phone_number = db.Column(db.String(20), nullable=False)
    menu_choice  = db.Column(db.String(100), nullable=False)
    timestamp    = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "id":           self.id,
            "phone_number": self.phone_number,
            "menu_choice":  self.menu_choice,
            "timestamp":    self.timestamp.isoformat(),
        }


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "OK"}), 200


@app.route("/log-call", methods=["POST"])
def log_call():
    data = request.get_json(silent=True)

    if not data:
        return jsonify({"error": "Request body must be JSON"}), 400

    phone_number = data.get("phone_number")
    menu_choice  = data.get("menu_choice")

    if not phone_number or not menu_choice:
        return jsonify({"error": "phone_number and menu_choice are required"}), 400

    call = CallLog(phone_number=phone_number, menu_choice=menu_choice)
    db.session.add(call)
    db.session.commit()

    return jsonify({"status": "saved", "call": call.to_dict()}), 201


@app.route("/call-logs", methods=["GET"])
def get_call_logs():
    logs = CallLog.query.order_by(CallLog.timestamp.desc()).all()
    return jsonify({"count": len(logs), "calls": [log.to_dict() for log in logs]}), 200


if __name__ == "__main__":
    app.run(port=5001, debug=True)
