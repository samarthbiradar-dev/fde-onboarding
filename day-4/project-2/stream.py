import os
import time

from dotenv import load_dotenv
from groq import Groq

load_dotenv()

QUESTION = "What is Plivo and what does it do?"
MODEL    = "llama-3.3-70b-versatile"

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

print(f"Question: {QUESTION}\n")
print("Answer:")

start           = time.perf_counter()
time_to_first   = None
total_tokens    = 0
answer_tokens   = 0
full_answer     = []

stream = client.chat.completions.create(
    model=MODEL,
    messages=[{"role": "user", "content": QUESTION}],
    stream=True,
)

for chunk in stream:
    token = chunk.choices[0].delta.content or ""

    if token and time_to_first is None:
        time_to_first = time.perf_counter() - start

    if token:
        print(token, end="", flush=True)
        full_answer.append(token)
        answer_tokens += 1

    if chunk.x_groq and chunk.x_groq.usage:
        total_tokens = chunk.x_groq.usage.total_tokens

elapsed = time.perf_counter() - start

print(f"\n\n--- Stats ---")
print(f"Model:              {MODEL}")
print(f"Time to first token:{time_to_first:.3f}s")
print(f"Total time:         {elapsed:.2f}s")
print(f"Tokens streamed:    {answer_tokens}")
print(f"Total tokens:       {total_tokens or answer_tokens}")
