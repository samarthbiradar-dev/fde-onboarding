import json
import math
import urllib.parse
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_TZ_ALIASES = {
    "IST": "Asia/Kolkata", "EST": "America/New_York", "EDT": "America/New_York",
    "PST": "America/Los_Angeles", "PDT": "America/Los_Angeles",
    "CST": "America/Chicago", "GMT": "Europe/London", "BST": "Europe/London",
    "JST": "Asia/Tokyo", "SGT": "Asia/Singapore", "AEST": "Australia/Sydney",
    "ICT": "Asia/Bangkok", "GST": "Asia/Dubai", "CET": "Europe/Paris",
    "MSK": "Europe/Moscow", "BRT": "America/Sao_Paulo",
}


def get_current_time(timezone: str = "UTC") -> dict:
    tz_name = _TZ_ALIASES.get(timezone.upper(), timezone)
    try:
        tz  = ZoneInfo(tz_name)
        now = datetime.now(tz)
        return {
            "time":       now.strftime("%H:%M:%S"),
            "date":       now.strftime("%Y-%m-%d"),
            "day":        now.strftime("%A"),
            "timezone":   tz_name,
            "utc_offset": now.strftime("%z"),
        }
    except ZoneInfoNotFoundError:
        now = datetime.now(ZoneInfo("UTC"))
        return {"error": f"Unknown timezone '{timezone}'. Try an IANA name like 'Asia/Bangkok'."}


def get_weather(city: str) -> dict:
    try:
        url = f"https://wttr.in/{urllib.parse.quote(city)}?format=j1"
        with urllib.request.urlopen(url, timeout=5) as r:
            data = json.loads(r.read())
        cur  = data["current_condition"][0]
        area = data["nearest_area"][0]
        return {
            "city":        f"{area['areaName'][0]['value']}, {area['country'][0]['value']}",
            "temperature": f"{cur['temp_C']}°C ({cur['temp_F']}°F)",
            "feels_like":  f"{cur['FeelsLikeC']}°C",
            "condition":   cur["weatherDesc"][0]["value"],
            "humidity":    f"{cur['humidity']}%",
            "wind":        f"{cur['windspeedKmph']} km/h {cur['winddir16Point']}",
            "visibility":  f"{cur['visibility']} km",
        }
    except Exception as e:
        return {"error": f"Could not fetch weather for '{city}': {e}"}


def calculate(expression: str) -> dict:
    # safe eval — only math operations, no builtins
    allowed = {k: getattr(math, k) for k in dir(math) if not k.startswith("_")}
    allowed.update({"abs": abs, "round": round, "pow": pow})
    try:
        result = eval(expression, {"__builtins__": {}}, allowed)  # noqa: S307
        return {"expression": expression, "result": result}
    except Exception as e:
        return {"error": f"Could not evaluate '{expression}': {e}"}


def convert_currency(amount: float, from_currency: str, to_currency: str) -> dict:
    try:
        url = f"https://open.er-api.com/v6/latest/{from_currency.upper()}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read())
        to  = to_currency.upper()
        if to not in data["rates"]:
            return {"error": f"Currency '{to}' not found"}
        rate      = data["rates"][to]
        converted = round(amount * rate, 4)
        return {
            "from":      f"{amount} {from_currency.upper()}",
            "to":        f"{converted} {to}",
            "rate":      rate,
            "updated":   data.get("time_last_update_utc", "unknown"),
        }
    except Exception as e:
        return {"error": f"Currency conversion failed: {e}"}


# ── Tool schemas ──────────────────────────────────────────────────────────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "Returns the current date and time for any city or timezone.",
            "parameters": {
                "type": "object",
                "properties": {
                    "timezone": {
                        "type": "string",
                        "description": "IANA timezone (e.g. 'Asia/Bangkok') or abbreviation (IST, EST, JST).",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Returns live current weather for any city worldwide.",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "City name, e.g. 'Bangkok', 'London'."}
                },
                "required": ["city"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": "Evaluates a math expression. Use for percentages, compound interest, unit math, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "Python math expression, e.g. '1000 * 1.07**10' or '0.15 * 47.50'.",
                    }
                },
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "convert_currency",
            "description": "Converts an amount from one currency to another using live exchange rates.",
            "parameters": {
                "type": "object",
                "properties": {
                    "amount":        {"type": "number", "description": "Amount to convert."},
                    "from_currency": {"type": "string", "description": "Source currency code, e.g. 'USD'."},
                    "to_currency":   {"type": "string", "description": "Target currency code, e.g. 'INR'."},
                },
                "required": ["amount", "from_currency", "to_currency"],
            },
        },
    },
]


def call_tool(name: str, args: dict) -> str:
    dispatch = {
        "get_current_time": get_current_time,
        "get_weather":      get_weather,
        "calculate":        calculate,
        "convert_currency": convert_currency,
    }
    fn = dispatch.get(name)
    if fn:
        return json.dumps(fn(**args))
    return json.dumps({"error": f"Unknown tool: {name}"})
