# Day 4 Project 2 — Streaming LLM Response

A Python script that streams the LLM response **token-by-token** as it arrives, and separately measures **time-to-first-token (TTFT)** vs total response time.

## What it does

- Opens a streaming connection to Groq (Llama 3.3 70B)
- Prints each token to the terminal as it arrives (`flush=True`)
- Records the exact moment the first token lands → TTFT
- Reports TTFT, total time, and token count at the end

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# paste your Groq API key into .env
```

## Run

```bash
python3 stream.py
```

## Example output

```
Question: What is Plivo and what does it do?

Answer:
Plivo is a cloud-based communication platform that provides a range of
APIs and services for building, scaling, and operating various types of
communication applications...

--- Stats ---
Model:              llama-3.3-70b-versatile
Time to first token:0.234s
Total time:         2.11s
Tokens streamed:    433
Total tokens:       479
```

## Key concepts

| Concept | Where |
|---|---|
| Streaming | `stream=True` in `chat.completions.create` |
| Token-by-token print | `print(token, end="", flush=True)` |
| Time-to-first-token | `time.perf_counter()` recorded on first non-empty chunk |
| Final token count | `chunk.x_groq.usage` on the last chunk |

## TTFT vs Total Time

- **TTFT (0.234s)** — how long until the user sees the first word. This is what determines perceived responsiveness in a UI.
- **Total time (2.11s)** — how long until the full response is complete.
- The gap (~1.9s) is the stream duration — in a real app this maps to a typing/loading indicator.
