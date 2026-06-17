import json
from flask import Flask, request, jsonify

app = Flask(__name__)


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "OK"}), 200


@app.route("/webhook-test", methods=["POST"])
def webhook_test():
    print("\n" + "=" * 50)
    print("INCOMING WEBHOOK")
    print("=" * 50)

    # Headers
    print("\n[Headers]")
    for key, value in request.headers:
        print(f"  {key}: {value}")

    # Body
    print("\n[Body]")
    content_type = request.content_type or ""

    if "application/json" in content_type:
        data = request.get_json(silent=True)
        print(json.dumps(data, indent=2))
    elif "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
        data = request.form.to_dict()
        print(json.dumps(data, indent=2))
    else:
        data = request.get_data(as_text=True)
        print(data or "(empty body)")

    print("=" * 50 + "\n")

    return jsonify({"received": True}), 200


if __name__ == "__main__":
    app.run(port=5000, debug=True)
