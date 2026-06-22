import json
import os
import random
from datetime import datetime

# ── Real function ─────────────────────────────────────────────────────────────

def get_current_time(timezone: str = "UTC") -> dict:
    now = datetime.now()
    return {
        "time":     now.strftime("%H:%M:%S"),
        "date":     now.strftime("%Y-%m-%d"),
        "day":      now.strftime("%A"),
        "timezone": timezone,
    }


# ── Mock function ─────────────────────────────────────────────────────────────

_CONDITIONS = ["Sunny", "Partly Cloudy", "Cloudy", "Rainy", "Thunderstorms", "Windy"]

def get_weather(city: str) -> dict:
    random.seed(sum(ord(c) for c in city))   # same city → same "weather" each run
    temp_c = random.randint(10, 38)
    return {
        "city":        city,
        "temperature": f"{temp_c}°C ({round(temp_c * 9/5 + 32)}°F)",
        "condition":   random.choice(_CONDITIONS),
        "humidity":    f"{random.randint(30, 90)}%",
        "wind":        f"{random.randint(5, 40)} km/h",
        "note":        "mock data",
    }


# ── Tool registry ─────────────────────────────────────────────────────────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name":        "get_current_time",
            "description": "Returns the current date and time.",
            "parameters": {
                "type":       "object",
                "properties": {
                    "timezone": {
                        "type":        "string",
                        "description": "Timezone name, e.g. 'UTC', 'IST', 'EST'. Optional.",
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
            "description": "Returns current weather for a given city.",
            "parameters": {
                "type":       "object",
                "properties": {
                    "city": {
                        "type":        "string",
                        "description": "Name of the city, e.g. 'Bangalore', 'London'.",
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
