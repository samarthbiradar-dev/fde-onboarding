# Day 4 Project 3 — Terminal Chatbot with Memory

An interactive terminal chatbot powered by **Llama 3.3 70B via Groq** that remembers everything said earlier in the conversation.

## What it does

- Accepts free-form input in a loop
- Maintains the full conversation history in memory
- Passes the entire history to the model on every turn so it remembers context
- Streams responses token-by-token as they arrive
- Built-in `history` command to review the conversation

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# paste your Groq API key into .env
```

## Run

Open a real terminal (not an IDE run button) and run:

```bash
python3 chat.py
```

## Commands

| Input | What happens |
|---|---|
| Any text | Sends message, streams the reply |
| `history` | Prints a preview of every message so far |
| `quit` / `exit` | Exits the chatbot |

## How memory works

Every message (user and assistant) is appended to a `history` list. On each turn the **entire list** is sent to the model, so it has full context of everything said before. The system prompt at index 0 sets the assistant's behaviour.

```
history = [
  { role: "system",    content: "You are a helpful assistant..." },
  { role: "user",      content: "My name is Samarth" },
  { role: "assistant", content: "Nice to meet you, Samarth!" },
  { role: "user",      content: "What is my name?" },   <-- new turn
]
```

The model sees all prior turns and answers: *"Your name is Samarth."*

## Key concepts

| Concept | Where |
|---|---|
| Conversation history | `history` list, appended every turn |
| Streaming replies | `stream=True`, `print(token, end="", flush=True)` |
| System prompt | First message with `role: "system"` |
| Graceful exit | Catches `KeyboardInterrupt` and `EOFError` |
