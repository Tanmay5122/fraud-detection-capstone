import os
from dotenv import load_dotenv

load_dotenv()

from pathlib import Path

# Force correct path
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(env_path)

# ── OpenRouter LLM ────────────────────────────────────────────────────────────
OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
OPENROUTER_MODEL: str = os.getenv("OPENROUTER_MODEL", "mistralai/mistral-7b-instruct:free")

# ── Database ──────────────────────────────────────────────────────────────────
DB_PATH: str = os.getenv("DB_PATH", "data/fraud_detection.db")

# ── Paths ─────────────────────────────────────────────────────────────────────
USER_PROFILES_PATH: str = "data/raw/user_profiles.json"
TRANSACTIONS_CSV: str   = "data/processed/transactions_clean.csv"

# ── Rule engine thresholds ────────────────────────────────────────────────────
AMOUNT_THRESHOLD: float   = 10_000.0   # ₹
VELOCITY_WINDOW_MINS: int = 10
VELOCITY_MAX_TXNS: int    = 3
GEO_DISTANCE_KM: float    = 500.0
ODD_HOURS_START: int      = 23          # 11 PM
ODD_HOURS_END: int        = 4           # 4 AM
ODD_HOURS_AMOUNT: float   = 5_000.0    # ₹

# ── FastAPI ───────────────────────────────────────────────────────────────────
API_HOST: str = "0.0.0.0"
API_PORT: int = 8000

# ── SMTP (Phase 5) ────────────────────────────────────────────────────────────
SMTP_HOST: str     = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT: int     = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER: str     = os.getenv("SMTP_USER", "")
SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
ALERT_RECIPIENT: str = os.getenv("ALERT_RECIPIENT", "")