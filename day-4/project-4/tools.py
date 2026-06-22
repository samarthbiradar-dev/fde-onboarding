import json
import urllib.parse
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Common abbreviations → IANA timezone names
_TZ_ALIASES = {
    "IST":  "Asia/Kolkata",
    "EST":  "America/New_York",
    "EDT":  "America/New_York",
    "PST":  "America/Los_Angeles",
    "PDT":  "America/Los_Angeles",
    "CST":  "America/Chicago",
    "CDT":  "America/Chicago",
    "MST":  "America/Denver",
    "GMT":  "Europe/London",
    "BST":  "Europe/London",
    "CET":  "Europe/Paris",
    "JST":  "Asia/Tokyo",
    "AEST": "Australia/Sydney",
    "SGT":  "Asia/Singapore",
}


def get_current_time(timezone: str = "UTC") -> dict:
    tz_name = _TZ_ALIASES.get(timezone.upper(), timezone)
    try:
        tz  = ZoneInfo(tz_name)
        now = datetime.now(tz)
        return {
            "time":     now.strftime("%H:%M:%S"),
            "date":     now.strftime("%Y-%m-%d"),
            "day":      now.strftime("%A"),
            "timezone": tz_name,
            "utc_offset": now.strftime("%z"),
        }
    except ZoneInfoNotFoundError:
        # fallback to UTC if timezone is unrecognised
        now = datetime.now(ZoneInfo("UTC"))
        return {
            "time":     now.strftime("%H:%M:%S"),
            "date":     now.strftime("%Y-%m-%d"),
            "day":      now.strftime("%A"),
            "timezone": "UTC (fallback — unknown timezone requested)",
            "utc_offset": "+0000",
        }


def get_weather(city: str) -> dict:
    try:
        url = f"https://wttr.in/{urllib.parse.quote(city)}?format=j1"
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read())

        current = data["current_condition"][0]
        area    = data["nearest_area"][0]
        area_name = area["areaName"][0]["value"]
        country   = area["country"][0]["value"]

        return {
            "city":        f"{area_name}, {country}",
            "temperature": f"{current['temp_C']}°C ({current['temp_F']}°F)",
            "feels_like":  f"{current['FeelsLikeC']}°C",
            "condition":   current["weatherDesc"][0]["value"],
            "humidity":    f"{current['humidity']}%",
            "wind":        f"{current['windspeedKmph']} km/h {current['winddir16Point']}",
            "visibility":  f"{current['visibility']} km",
        }
    except Exception as e:
        return {"error": f"Could not fetch weather for '{city}': {e}"}


# ── Tool registry ─────────────────────────────────────────────────────────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name":        "get_current_time",
            "description": "Returns the current local date and time for a given timezone.",
            "parameters": {
                "type":       "object",
                "properties": {
                    "timezone": {
                        "type":        "string",
                        "description": (
                            "Timezone to use. Accepts IANA names (e.g. 'Asia/Kolkata', "
                            "'America/New_York') or common abbreviations like 'IST', 'EST', 'PST'."
                        ),
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "get_weather",
            "description": "Returns live current weather for a given city.",
            "parameters": {
                "type":       "object",
                "properties": {
                    "city": {
                        "type":        "string",
                        "description": "City name, e.g. 'Bangalore', 'London', 'New York'.",
                    }
                },
                "required": ["city"],
            },
        },
    },
]


def call_tool(name: str, args: dict) -> str:
    if name == "get_current_time":
        result = get_current_time(**args)
    elif name == "get_weather":
        result = get_weather(**args)
    else:
        result = {"error": f"Unknown tool: {name}"}
    return json.dumps(result)

