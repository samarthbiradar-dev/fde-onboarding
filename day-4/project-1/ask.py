import os
import time

from dotenv import load_dotenv
from groq import Groq

load_dotenv()

QUESTION = "What is Plivo and what does it do?"
MODEL    = "llama-3.3-70b-versatile"

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

print(f"Question: {QUESTION}\n")

start    = time.perf_counter()
response = client.chat.completions.create(
    model=MODEL,
    messages=[{"role": "user", "content": QUESTION}],
)
elapsed  = time.perf_counter() - start

answer = response.choices[0].message.content
tokens = response.usage

print(f"Answer:\n{answer}\n")
print(f"--- Stats ---")
print(f"Model:          {MODEL}")
print(f"Time taken:     {elapsed:.2f}s")
print(f"Prompt tokens:  {tokens.prompt_tokens}")
print(f"Answer tokens:  {tokens.completion_tokens}")
print(f"Total tokens:   {tokens.total_tokens}")
