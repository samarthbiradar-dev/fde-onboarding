import json
import os

from dotenv import load_dotenv
from groq import Groq

from tools import TOOLS, call_tool

load_dotenv()

MODEL  = "llama-3.3-70b-versatile"
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

history = [
    {
        "role":    "system",
        "content": (
            "You are a helpful assistant with access to two tools: "
            "get_current_time and get_weather. "
            "Only call a tool when the user is actually asking for the time or weather. "
            "For everything else, answer directly."
        ),
    }
]


def run_turn(user_input: str):
    history.append({"role": "user", "content": user_input})

    # ── First call: model decides whether to use a tool ──────────────────────
    response = client.chat.completions.create(
        model=MODEL,
        messages=history,
        tools=TOOLS,
        tool_choice="auto",
    )

    msg = response.choices[0].message

    # ── No tool call: stream a direct answer ──────────────────────────────────
    if not msg.tool_calls:
        history.append({"role": "assistant", "content": msg.content})
        print(f"\nAssistant: {msg.content}\n")
        return

    # ── Tool call(s): execute each one ────────────────────────────────────────
    history.append(msg)   # add the assistant's tool-call message

    for tc in msg.tool_calls:
        name = tc.function.name
        args = json.loads(tc.function.arguments)

        print(f"\n[Tool call] {name}({args})")
        result = call_tool(name, args)
        print(f"[Tool result] {result}")

        history.append({
            "role":         "tool",
            "tool_call_id": tc.id,
            "content":      result,
        })

    # ── Second call: model formulates the final answer using tool results ─────
    final = client.chat.completions.create(
        model=MODEL,
        messages=history,
        tools=TOOLS,
    )

    final_content = final.choices[0].message.content
    history.append({"role": "assistant", "content": final_content})
    print(f"\nAssistant: {final_content}\n")


def main():
    print(f"Function-calling chatbot ({MODEL} via Groq)")
    print("Tools available: get_current_time, get_weather")
    print("Type 'quit' to exit.\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit"):
            print("Bye!")
            break

        run_turn(user_input)


if __name__ == "__main__":
    main()
