"""
Quick OpenRouter connection debugger.
Run: python test_connection.py
"""

import urllib.request
import urllib.error
import json
import os
from dotenv import load_dotenv

load_dotenv()
key = os.getenv("OPENROUTER_API_KEY", "")

print("\n── OpenRouter Connection Debug ──\n")
print(f"  Key found   : {'✅ Yes' if key else '❌ No'}")
print(f"  Key preview : {key[:12]}...{key[-4:] if len(key) > 16 else '(too short)'}")
print(f"  Key length  : {len(key)} chars (expected ~76)\n")

# ── Step 1: basic internet check ────────────────────────────────────────────
print("  Step 1 — Checking internet connectivity...")
try:
    urllib.request.urlopen("https://openrouter.ai", timeout=10)
    print("  ✅ Can reach openrouter.ai\n")
except Exception as e:
    print(f"  ❌ Cannot reach openrouter.ai — {e}")
    print("     → Check your internet / firewall / VPN settings\n")
    exit(1)

# ── Step 2: auth check (list models) ────────────────────────────────────────
print("  Step 2 — Checking API key authentication...")
try:
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/models",
        headers={"Authorization": f"Bearer {key}"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())
    free_models = [m["id"] for m in data.get("data", []) if ":free" in m["id"]]
    print(f"  ✅ Auth OK — {len(free_models)} free models available")
    print(f"     First few: {free_models[:3]}\n")
except urllib.error.HTTPError as e:
    body = e.read().decode()
    print(f"  ❌ Auth failed — HTTP {e.code}: {e.reason}")
    print(f"     Response: {body[:300]}\n")
    exit(1)
except Exception as e:
    print(f"  ❌ Unexpected error — {e}\n")
    exit(1)

# ── Step 3: actual generation call ──────────────────────────────────────────
print("  Step 3 — Sending test generation request...")

models_to_try = [
    "openrouter/free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "mistralai/mistral-7b-instruct:free",
    "google/gemma-3-4b-it:free",
]

for model in models_to_try:
    print(f"     Trying model: {model} ...", end=" ", flush=True)
    try:
        payload = json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": "Reply with exactly: SYSTEM OK"}],
            "max_tokens": 20,
        }).encode()

        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=payload,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/Tanmay5122/fraud-detection-capstone",
                "X-Title": "Fraud Detection Capstone",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())

        text = data["choices"][0]["message"]["content"]
        print(f"✅ Works! Response: '{text.strip()}'")
        print(f"\n  ✅ Use this model in your .env:")
        print(f"     OPENROUTER_MODEL={model}\n")
        break

    except urllib.error.HTTPError as e:
        body = e.read().decode()[:200]
        print(f"❌ HTTP {e.code} — {body}")
    except Exception as e:
        print(f"❌ {e}")
else:
    print("\n  ❌ All models failed — see errors above\n")