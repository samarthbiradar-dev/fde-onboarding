# Day 4 Project 4 — Function Calling Chatbot

A terminal chatbot that gives the LLM access to real tools. The model decides **on its own** when to call a function vs answer directly.

## Tools available

| Tool | Type | What it does |
|---|---|---|
| `get_current_time` | Real | Returns actual local time for any timezone |
| `get_weather` | Live | Fetches live weather from wttr.in (no API key needed) |

## What it does

- Sends user messages to Groq with tool definitions attached
- If the model decides a tool is needed, it returns a `tool_call` instead of text
- The script executes the tool locally and sends the result back
- The model then formulates a natural-language answer using the tool result
- For questions that don't need tools, the model answers directly

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# paste your Groq API key into .env
```

## Run

Open a real terminal and run:

```bash
python3 chat.py
```

## Try these prompts

| Prompt | Tool called |
|---|---|
| "What time is it in Tokyo?" | `get_current_time(timezone="JST")` |
| "What's the weather in Bangalore?" | `get_weather(city="Bangalore")` |
| "What time is it in New York?" | `get_current_time(timezone="America/New_York")` |
| "Who invented the telephone?" | *(no tool — answered directly)* |

## How function calling works (two-turn pattern)

```
Turn 1: user message + tool definitions → model returns tool_call
         ↓
         script executes the function locally
         ↓
Turn 2: original messages + tool result → model returns final answer
```

The model never runs code itself — it only **requests** a function call with arguments. The script decides whether to honour it.

## Supported timezones

Accepts both IANA names and common abbreviations:

| Abbreviation | IANA name |
|---|---|
| IST | Asia/Kolkata |
| EST | America/New_York |
| PST | America/Los_Angeles |
| JST | Asia/Tokyo |
| GMT | Europe/London |

## Files

| File | Purpose |
|---|---|
| `chat.py` | Main chatbot loop, handles tool-call flow |
| `tools.py` | Tool implementations + JSON schema definitions for the model |
