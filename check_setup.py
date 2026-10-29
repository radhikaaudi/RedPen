"""Verify the Token Factory key works and that the Nemotron models Redpen needs are available.

Run:  python check_setup.py
"""

import os
import sys

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

api_key = os.getenv("NEBIUS_API_KEY")
if not api_key or api_key.startswith("your-"):
    sys.exit("NEBIUS_API_KEY is missing. Copy .env.example to .env and paste your key.")

client = OpenAI(
    base_url=os.getenv("NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1/"),
    api_key=api_key,
)

print("1) Listing NVIDIA / Nemotron models available to your key...")
models = sorted(m.id for m in client.models.list().data)
nemotron = [m for m in models if "nemotron" in m.lower()]
for m in nemotron:
    print("   -", m)
if not nemotron:
    print("   (none found — showing all nvidia/* models)")
    for m in models:
        if m.lower().startswith("nvidia/"):
            print("   -", m)

print("\n2) Checking the models configured in .env...")
roles = {
    "MODEL_VISION": os.getenv("MODEL_VISION"),
    "MODEL_FAST": os.getenv("MODEL_FAST"),
    "MODEL_REASONING": os.getenv("MODEL_REASONING"),
}
all_ok = True
for role, model in roles.items():
    ok = model in models
    all_ok &= ok
    print(f"   {'OK ' if ok else 'MISSING'}  {role} = {model}")

print("\n3) Test call to the fast model...")
fast = roles["MODEL_FAST"] if roles["MODEL_FAST"] in models else (nemotron[0] if nemotron else None)
if fast:
    reply = client.chat.completions.create(
        model=fast,
        messages=[{"role": "user", "content": "Reply with exactly: Redpen is ready."}],
        max_tokens=50,
    )
    print(f"   {fast} says: {reply.choices[0].message.content!r}")
else:
    print("   Skipped — no Nemotron model available.")

if not all_ok:
    print("\nSome configured model IDs were not found. Update MODEL_* in .env using the list above.")
