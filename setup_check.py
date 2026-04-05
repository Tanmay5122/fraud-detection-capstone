"""
Run this script after setup to verify everything is working.
Uses OpenRouter API (free tier, no billing required).
Usage: python setup_check.py
"""

import sys
import importlib
import time


def check(label: str, fn):
    try:
        fn()
        print(f"  ✅  {label}")
        return True
    except Exception as e:
        print(f"  ❌  {label} — {e}")
        return False


def check_python_version():
    assert sys.version_info >= (3, 10), f"Python 3.10+ required, got {sys.version}"


def check_import(pkg):
    importlib.import_module(pkg)


def check_env_file():
    from pathlib import Path
    assert Path(".env").exists(), ".env file not found"


def _get_key():
    from dotenv import load_dotenv
    import os
    load_dotenv()
    return os.getenv("OPENROUTER_API_KEY", "")


def _get_model():
    from dotenv import load_dotenv
    import os
    load_dotenv()
    return os.getenv("OPENROUTER_MODEL", "openrouter/free")


def check_openrouter_key():
    key = _get_key()
    assert key and len(key) > 20, (
        "OPENROUTER_API_KEY not set — get a free key at https://openrouter.ai/keys"
    )


def check_openrouter_connection():
    import urllib.request
    import json

    key   = _get_key()
    model = _get_model()

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
    assert "OK" in text.upper(), f"Unexpected response: {text}"


def check_openrouter_connection_with_retry():
    last_err = None
    for attempt in range(3):
        try:
            check_openrouter_connection()
            return
        except Exception as e:
            last_err = e
            err_str = str(e)
            if "429" in err_str or "rate" in err_str.lower():
                wait = 15 * (attempt + 1)
                print(f"\n  ⏳ Rate-limit, waiting {wait}s (retry {attempt+1}/3)...", end="", flush=True)
                time.sleep(wait)
                print(" retrying.")
            else:
                raise
    raise last_err


def check_data_dirs():
    from pathlib import Path
    for d in ["data/raw", "data/processed", "logs", "outputs"]:
        Path(d).mkdir(parents=True, exist_ok=True)


print("\n── Fraud Detection Capstone — Environment Check ──\n")

results = [
    check("Python 3.10+",               check_python_version),
    check("pandas",                     lambda: check_import("pandas")),
    check("fastapi",                    lambda: check_import("fastapi")),
    check("requests",                   lambda: check_import("requests")),
    check("sqlalchemy",                 lambda: check_import("sqlalchemy")),
    check("faker",                      lambda: check_import("faker")),
    check("reportlab",                  lambda: check_import("reportlab")),
    check(".env file exists",           check_env_file),
    check("OPENROUTER_API_KEY in .env", check_openrouter_key),
    check("OpenRouter API connection",  check_openrouter_connection_with_retry),
    check("data/logs/outputs dirs",     check_data_dirs),
]

print()
passed = sum(results)
total  = len(results)

if passed == total:
    print(f"  🎉 All {total} checks passed — you're ready for Phase 2!\n")
else:
    print(f"  ⚠️   {passed}/{total} checks passed — fix the ❌ items above before continuing.\n")