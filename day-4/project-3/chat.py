import os

from dotenv import load_dotenv
from groq import Groq

load_dotenv()

MODEL  = "llama-3.3-70b-versatile"
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

SYSTEM_PROMPT = (
    "You are a helpful assistant. You remember everything said earlier "
    "in the conversation and refer back to it when relevant."
)

history = [{"role": "system", "content": SYSTEM_PROMPT}]


def chat(user_input: str) -> str:
    history.append({"role": "user", "content": user_input})

    stream = client.chat.completions.create(
        model=MODEL,
        messages=history,
        stream=True,
    )

    print("\nAssistant: ", end="", flush=True)
    reply = []
    for chunk in stream:
        token = chunk.choices[0].delta.content or ""
        print(token, end="", flush=True)
        reply.append(token)

    print("\n")
    full_reply = "".join(reply)
    history.append({"role": "assistant", "content": full_reply})
    return full_reply


def main():
    print("Chatbot ready (Llama 3.3 70B via Groq)")
    print("Type 'quit' or 'exit' to stop, 'history' to see the conversation.\n")

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

        if user_input.lower() == "history":
            print("\n--- Conversation History ---")
            for msg in history:
                if msg["role"] == "system":
                    continue
                label = "You" if msg["role"] == "user" else "Assistant"
                preview = msg["content"][:120].replace("\n", " ")
                print(f"  [{label}] {preview}{'...' if len(msg['content']) > 120 else ''}")
            print("---\n")
            continue

        chat(user_input)


if __name__ == "__main__":
    main()
