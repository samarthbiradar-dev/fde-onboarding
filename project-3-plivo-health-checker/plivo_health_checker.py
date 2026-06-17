import os
import sys
from datetime import datetime
from dotenv import load_dotenv

import plivo
from plivo.exceptions import AuthenticationError
import requests


ENV_FILE = os.path.join(os.path.dirname(__file__), ".env")


def load_credentials():
    if not os.path.exists(ENV_FILE):
        print("Error: .env file not found")
        sys.exit(1)

    load_dotenv(ENV_FILE)

    auth_id = os.getenv("PLIVO_AUTH_ID")
    auth_token = os.getenv("PLIVO_AUTH_TOKEN")

    if not auth_id or not auth_token:
        print("Error: PLIVO_AUTH_ID and PLIVO_AUTH_TOKEN must be set in .env")
        sys.exit(1)

    return auth_id, auth_token


def get_account(client):
    try:
        return client.account.get()
    except AuthenticationError:
        print("Error: Invalid Plivo credentials")
        sys.exit(1)
    except requests.exceptions.ConnectionError:
        print("Error: Cannot connect to Plivo")
        sys.exit(1)


def get_messages(client):
    try:
        response = client.messages.list(limit=10, offset=0)
        return response["objects"] if isinstance(response, dict) else list(response)[:10]
    except AuthenticationError:
        print("Error: Invalid Plivo credentials")
        sys.exit(1)
    except requests.exceptions.ConnectionError:
        print("Error: Cannot connect to Plivo")
        sys.exit(1)


def format_timestamp(ts):
    if not ts:
        return "N/A"
    try:
        dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S.%f%z")
    except ValueError:
        try:
            dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S%z")
        except ValueError:
            return ts
    return dt.strftime("%d %b %Y  %H:%M UTC")


def status_badge(status):
    badges = {
        "delivered": "✓ delivered",
        "sent":      "→ sent",
        "failed":    "✗ failed",
        "queued":    "⏳ queued",
        "rejected":  "✗ rejected",
        "undelivered": "✗ undelivered",
    }
    return badges.get((status or "").lower(), status or "unknown")


def print_report(account, messages):
    width = 64
    line  = "─" * width

    print()
    print("┌" + line + "┐")
    print("│{:^64}│".format("PLIVO ACCOUNT HEALTH REPORT"))
    print("├" + line + "┤")

    # Account status
    cash_credits = getattr(account, "cash_credits", None)
    balance = f"${float(cash_credits):.4f} USD" if cash_credits is not None else "N/A"
    account_status = "✓  OK" if cash_credits is not None else "✗  ERROR"

    print("│  {:<30} {:>30}  │".format("Status", account_status))
    print("│  {:<30} {:>30}  │".format("Balance", balance))
    print("│  {:<30} {:>30}  │".format("Account Name", getattr(account, "name", "N/A") or "N/A"))
    print("│  {:<30} {:>30}  │".format("Auth ID", getattr(account, "auth_id", "N/A") or "N/A"))
    print("├" + line + "┤")
    print("│{:^64}│".format("LAST 10 MESSAGES"))
    print("├" + line + "┤")

    if not messages:
        print("│{:^64}│".format("No messages found"))
    else:
        print("│  {:<22} {:<15} {:<20}  │".format("Timestamp", "To", "Status"))
        print("│  " + "─" * 22 + " " + "─" * 15 + " " + "─" * 20 + "  │")
        for msg in messages:
            if isinstance(msg, dict):
                ts     = msg.get("message_time") or msg.get("creation_time", "")
                to_num = msg.get("to_number", "N/A")
                status = msg.get("message_state") or msg.get("status", "")
            else:
                ts     = getattr(msg, "message_time", None) or getattr(msg, "creation_time", "")
                to_num = getattr(msg, "to_number", "N/A")
                status = getattr(msg, "message_state", None) or getattr(msg, "status", "")

            ts_fmt  = format_timestamp(str(ts)) if ts else "N/A"
            to_fmt  = str(to_num)[:15]
            st_fmt  = status_badge(status)[:20]
            print("│  {:<22} {:<15} {:<20}  │".format(ts_fmt[:22], to_fmt, st_fmt))

    print("└" + line + "┘")
    print()


def main():
    auth_id, auth_token = load_credentials()

    try:
        client = plivo.RestClient(auth_id=auth_id, auth_token=auth_token)
    except Exception:
        print("Error: Cannot connect to Plivo")
        sys.exit(1)

    account  = get_account(client)
    messages = get_messages(client)
    print_report(account, messages)


if __name__ == "__main__":
    main()
