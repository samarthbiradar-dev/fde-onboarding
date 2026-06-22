# Day 4 Project 1 — Single LLM API Call

A minimal Python script that sends one question to **Llama 3.3 70B** via the Groq API, prints the answer, and reports how long the call took.

## What it does

- Loads the API key from a `.env` file
- Sends a hardcoded question to the model
- Prints the full answer
- Prints model name, time taken, and token usage

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# paste your Groq API key into .env
```

Get a free Groq API key at https://console.groq.com/keys

## Run

```bash
python3 ask.py
```

## Example output

```
Question: What is Plivo and what does it do?

Answer:
Plivo is a cloud-based communication platform that provides a suite of
APIs and tools for building voice and messaging applications...

--- Stats ---
Model:          llama-3.3-70b-versatile
Time taken:     1.97s
Prompt tokens:  45
Answer tokens:  423
Total tokens:   468
```

## Key concepts

| Concept | Where |
|---|---|
| API key from env | `load_dotenv()` + `os.getenv("GROQ_API_KEY")` |
| Chat completion | `client.chat.completions.create(model, messages)` |
| Token usage | `response.usage.prompt_tokens / completion_tokens` |
| Timing | `time.perf_counter()` before and after the call |
