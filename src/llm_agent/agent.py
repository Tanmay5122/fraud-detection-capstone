"""
LLM Reasoning Agent — Phase 4
Reads suspects from the suspect_queue table, enriches with user profile context,
calls OpenRouter API for a structured verdict, and logs to llm_decisions table.

This is the core research contribution: every decision includes a natural-language
reasoning paragraph for explainability comparison against rule-only detection.
"""

import json
import logging
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from openai import OpenAI

from src.config import (
    DB_PATH,
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    OPENROUTER_MODEL,
    USER_PROFILES_PATH,
)

logger = logging.getLogger(__name__)

# ── Structured output schema (parsed from LLM JSON response) ─────────────────
SYSTEM_PROMPT = """You are an expert fraud analyst for an Indian retail bank.
You will be given a suspicious banking transaction and the customer's recent history.
Your job is to decide if this is fraud or legitimate.

You MUST respond with ONLY valid JSON — no markdown, no explanation outside the JSON.
Use exactly this schema:
{
  "verdict": "FRAUD" | "LEGITIMATE" | "REVIEW",
  "confidence": <float 0.0–1.0>,
  "reasoning": "<2–4 sentence natural-language explanation of your decision>",
  "recommended_action": "FREEZE_ACCOUNT" | "SEND_ALERT" | "MONITOR" | "CLEAR"
}

Rules:
- FRAUD + confidence >= 0.75 → recommended_action must be FREEZE_ACCOUNT
- FRAUD + confidence < 0.75  → recommended_action must be SEND_ALERT
- REVIEW                      → recommended_action must be MONITOR
- LEGITIMATE                  → recommended_action must be CLEAR
"""


def _build_user_prompt(suspect_row: dict, profile: Optional[dict]) -> str:
    """Construct the per-transaction prompt with all available context."""
    txn_block = f"""
TRANSACTION UNDER REVIEW
─────────────────────────
Transaction ID : {suspect_row['transaction_id']}
User ID        : {suspect_row['user_id']}
Amount         : ₹{suspect_row['amount']:,.2f}
Type           : {suspect_row['transaction_type']}
Location       : {suspect_row['location']}
Timestamp      : {suspect_row['timestamp']}
Rules Triggered: {suspect_row['rules_triggered']}
Rule Score     : {suspect_row['rule_score']}
"""

    if profile:
        history_str = json.dumps(profile.get("recent_transactions", [])[:5], indent=2)
        profile_block = f"""
CUSTOMER PROFILE
─────────────────────────
Name            : {profile.get('name', 'N/A')}
City            : {profile.get('city', 'N/A')}
Account Type    : {profile.get('account_type', 'N/A')}
Avg Monthly Txn : ₹{profile.get('avg_monthly_transaction', 0):,.2f}
Known Locations : {', '.join(profile.get('known_locations', []))}
Risk Tier       : {profile.get('risk_tier', 'N/A')}

Recent Transaction History (last 5):
{history_str}
"""
    else:
        profile_block = "\nCUSTOMER PROFILE\n─────────────────────────\nNo profile found for this user.\n"

    return txn_block + profile_block + "\nAnalyse the transaction and respond with JSON only."


class FraudAgent:
    def __init__(self):
        if not OPENROUTER_API_KEY:
            raise ValueError("OPENROUTER_API_KEY not set in .env")

        self.client = OpenAI(
            api_key=OPENROUTER_API_KEY,
            base_url=OPENROUTER_BASE_URL,
        )
        self.model = OPENROUTER_MODEL
        self.profiles = self._load_profiles()
        logger.info(f"FraudAgent initialised — model: {self.model}")

    # ── Profile loading ───────────────────────────────────────────────────────

    def _load_profiles(self) -> dict:
     path = Path(USER_PROFILES_PATH)
     if not path.exists():
        logger.warning(f"User profiles not found at {USER_PROFILES_PATH}")
        return {}

     with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # ✅ Case 1: your JSON is already a dict
     if isinstance(data, dict):
        return data

    # ✅ Case 2: list of profiles
     if isinstance(data, list):
        return {p["user_id"]: p for p in data if isinstance(p, dict)}

     raise ValueError("Invalid user_profiles.json format")

    # ── Database helpers ──────────────────────────────────────────────────────

    def _get_pending_suspects(self, conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            """
            SELECT * FROM suspect_queue
            WHERE status = 'PENDING'
            ORDER BY queued_at ASC
            LIMIT ?
            """,
            (limit,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.row_factory = None
        return rows

    def _mark_processing(self, conn: sqlite3.Connection, suspect_id: int):
        conn.execute(
            "UPDATE suspect_queue SET status = 'PROCESSING' WHERE id = ?",
            (suspect_id,),
        )
        conn.commit()

    def _log_decision(self, conn: sqlite3.Connection, suspect: dict, decision: dict):
        conn.execute(
            """
            INSERT INTO llm_decisions
                (transaction_id, user_id, verdict, confidence,
                 reasoning, recommended_action, model_used, decided_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                suspect["transaction_id"],
                suspect["user_id"],
                decision["verdict"],
                decision["confidence"],
                decision["reasoning"],
                decision["recommended_action"],
                self.model,
                datetime.utcnow().isoformat(),
            ),
        )
        conn.execute(
            "UPDATE suspect_queue SET status = 'PROCESSED' WHERE id = ?",
            (suspect["id"],),
        )
        conn.commit()

    def _mark_error(self, conn: sqlite3.Connection, suspect_id: int, error: str):
        conn.execute(
            "UPDATE suspect_queue SET status = 'ERROR' WHERE id = ?",
            (suspect_id,),
        )
        conn.commit()
        logger.error(f"Suspect {suspect_id} marked ERROR: {error}")

    # ── LLM call ─────────────────────────────────────────────────────────────

    def _call_llm(self, prompt: str, retries: int = 2) -> dict:
        for attempt in range(retries + 1):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user",   "content": prompt},
                    ],
                    temperature=0.1,   # low temp for consistent structured output
                    max_tokens=400,
                )
                raw = response.choices[0].message.content.strip()

                # Strip accidental markdown fences
                if raw.startswith("```"):
                    raw = raw.split("```")[1]
                    if raw.startswith("json"):
                        raw = raw[4:]

                decision = json.loads(raw)

                # Validate required keys
                required = {"verdict", "confidence", "reasoning", "recommended_action"}
                if not required.issubset(decision.keys()):
                    raise ValueError(f"Missing keys in LLM response: {decision.keys()}")

                # Clamp confidence
                decision["confidence"] = max(0.0, min(1.0, float(decision["confidence"])))
                return decision

            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(f"LLM parse error (attempt {attempt+1}): {e}")
                if attempt == retries:
                    raise
                time.sleep(1)

        raise RuntimeError("LLM call failed after retries")

    # ── Main processing loop ──────────────────────────────────────────────────

    def process_batch(self, limit: int = 20) -> dict:
        """
        Process up to `limit` pending suspects.
        Returns a summary dict for logging/API responses.
        """
        conn = sqlite3.connect(DB_PATH)
        suspects = self._get_pending_suspects(conn, limit)

        if not suspects:
            logger.info("No pending suspects to process.")
            conn.close()
            return {"processed": 0, "fraud": 0, "legitimate": 0, "review": 0, "errors": 0}

        stats = {"processed": 0, "fraud": 0, "legitimate": 0, "review": 0, "errors": 0}

        for suspect in suspects:
            txn_id = suspect["transaction_id"]
            self._mark_processing(conn, suspect["id"])
            profile = self.profiles.get(suspect["user_id"])

            try:
                prompt   = _build_user_prompt(suspect, profile)
                decision = self._call_llm(prompt)
                self._log_decision(conn, suspect, decision)

                verdict = decision["verdict"]
                confidence = decision["confidence"]
                action = decision["recommended_action"]

                stats["processed"] += 1
                stats[verdict.lower() if verdict.lower() in stats else "review"] += 1

                icon = "🔴" if verdict == "FRAUD" else ("🟡" if verdict == "REVIEW" else "🟢")
                logger.info(
                    f"{icon} {txn_id} | {verdict} ({confidence:.0%}) | "
                    f"{action} | {decision['reasoning'][:80]}…"
                )

            except Exception as e:
                stats["errors"] += 1
                self._mark_error(conn, suspect["id"], str(e))

            time.sleep(0.3)   # polite rate-limiting for free-tier OpenRouter

        conn.close()
        logger.info(
            f"Batch complete — processed:{stats['processed']} "
            f"fraud:{stats['fraud']} legit:{stats['legitimate']} "
            f"review:{stats['review']} errors:{stats['errors']}"
        )
        return stats