import json
import logging
import sqlite3
import time
import random
from datetime import datetime
from pathlib import Path
from typing import Optional
import ast

from openai import OpenAI
from openai import RateLimitError

from src.config import (
    DB_PATH,
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    OPENROUTER_MODEL,
    USER_PROFILES_PATH,
)

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are an expert fraud analyst for an Indian retail bank.
You MUST respond ONLY with valid JSON.

{
  "verdict": "FRAUD" | "LEGITIMATE" | "REVIEW",
  "confidence": <float 0.0–1.0>,
  "reasoning": "<2–4 sentence explanation>",
  "recommended_action": "FREEZE_ACCOUNT" | "SEND_ALERT" | "MONITOR" | "CLEAR"
}
"""


def _build_user_prompt(suspect: dict, txn: dict, profile: Optional[dict]) -> str:
    txn_block = f"""
Transaction ID : {suspect.get('txn_id')}
User ID        : {suspect.get('user_id')}
Amount         : ₹{txn.get('amount')}
Category       : {txn.get('merchant_category')}
Location       : {txn.get('merchant_city')}
Timestamp      : {txn.get('timestamp')}
Rules Triggered: {suspect.get('rules_triggered')}
"""

    if profile:
        profile_block = f"""
Customer Profile:
Avg Spend: ₹{profile.get('avg_monthly_spend')}
Max Txn  : ₹{profile.get('typical_max_txn')}
"""
    else:
        profile_block = "\nNo profile\n"

    return txn_block + profile_block


class FraudAgent:
    def __init__(self):
        if not OPENROUTER_API_KEY:
            raise ValueError("OPENROUTER_API_KEY not set")

        self.client = OpenAI(
            api_key=OPENROUTER_API_KEY,
            base_url=OPENROUTER_BASE_URL,
        )

        self.model = OPENROUTER_MODEL
        self.profiles = self._load_profiles()

    def _load_profiles(self):
        path = Path(USER_PROFILES_PATH)

        if not path.exists():
            logger.warning(f"User profiles not found at {path}")
            return {}

        try:
            with open(path, "r") as f:
                data = json.load(f)

            if isinstance(data, dict):
                return data
            if isinstance(data, list):
                return {p["user_id"]: p for p in data}

            return {}
        except Exception as e:
            logger.error(f"Failed to load profiles: {e}")
            return {}

    def _get_pending_suspects(self, conn, limit):
        """Get suspects from DB - returns dict rows"""
        conn.row_factory = sqlite3.Row

        rows = conn.execute(
            """
            SELECT sq.*, t.*
            FROM suspect_queue sq
            LEFT JOIN transactions t ON t.txn_id = sq.txn_id
            WHERE sq.llm_processed = 0
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

        return [dict(r) for r in rows]

    def _safe_parse_list(self, value):
        """Safely convert string list to actual list"""
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            try:
                parsed = ast.literal_eval(value)
                if isinstance(parsed, list):
                    return parsed
                return [value]
            except:
                return [value]
        return []

    def _safe_parse_dict(self, value):
        """Safely convert string dict to actual dict"""
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                parsed = ast.literal_eval(value)
                if isinstance(parsed, dict):
                    return parsed
                return {"raw": value}
            except:
                return {"raw": value}
        return {}

    def _call_llm(self, prompt, txn_id=None):
        """
        Call OpenRouter API with AGGRESSIVE retry logic for free models.
        Free tier = strict rate limits (429 errors), so we need long waits + jitter.
        
        Strategy:
        - Attempt 1: Wait 5s
        - Attempt 2: Wait 10s
        - Attempt 3: Wait 20s
        - Attempt 4: Wait 40s
        - Attempt 5: Wait 80s
        (Plus random 0-2s jitter to avoid thundering herd)
        """
        max_retries = 5
        base_wait = 5  # Start with 5 seconds
        
        for attempt in range(max_retries):
            try:
                logger.info(f"[{txn_id}] 🚀 LLM attempt {attempt + 1}/{max_retries}...")

                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.7,
                    max_tokens=500,
                )

                raw = response.choices[0].message.content
                logger.debug(f"[{txn_id}] ✅ LLM response: {raw}")
                
                # Successfully got response - parse it
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    logger.error(f"[{txn_id}] ❌ Failed to parse JSON: {raw}")
                    return {
                        "verdict": "REVIEW",
                        "confidence": 0.5,
                        "reasoning": "JSON parsing error",
                        "recommended_action": "MONITOR",
                    }

            except RateLimitError as e:
                if attempt < max_retries - 1:
                    # Exponential backoff: 5s, 10s, 20s, 40s, 80s
                    wait_time = base_wait * (2 ** attempt)
                    
                    # Add random jitter to avoid thundering herd
                    jitter = random.uniform(0, 2)
                    total_wait = wait_time + jitter
                    
                    logger.warning(
                        f"[{txn_id}] ⏳ RATE LIMITED (429). "
                        f"Waiting {total_wait:.1f}s before retry {attempt + 2}/{max_retries}... "
                        f"(This is normal for free tier)"
                    )
                    time.sleep(total_wait)
                else:
                    logger.error(
                        f"[{txn_id}] ❌ RATE LIMITED after {max_retries} attempts. "
                        f"Will mark as REVIEW to try later."
                    )
                    return {
                        "verdict": "REVIEW",
                        "confidence": 0.2,
                        "reasoning": "LLM service rate limited. Will process in next batch.",
                        "recommended_action": "MONITOR",
                    }

            except Exception as e:
                logger.error(f"[{txn_id}] ❌ LLM error: {e}")
                return {
                    "verdict": "REVIEW",
                    "confidence": 0.3,
                    "reasoning": f"LLM service error",
                    "recommended_action": "MONITOR",
                }

        # Fallback
        return {
            "verdict": "REVIEW",
            "confidence": 0.2,
            "reasoning": "Could not reach LLM",
            "recommended_action": "MONITOR",
        }

    def process_batch(self, limit=20):
        """Process suspects and get LLM verdicts"""
        conn = sqlite3.connect(DB_PATH)

        try:
            suspects = self._get_pending_suspects(conn, limit)
            
            if not suspects:
                logger.info("No pending suspects to process")
                return {
                    "processed": 0,
                    "fraud": 0,
                    "legitimate": 0,
                    "review": 0,
                    "errors": 0,
                }
            
            logger.info(f"📊 Processing {len(suspects)} pending suspects...")

            stats = {
                "processed": 0,
                "fraud": 0,
                "legitimate": 0,
                "review": 0,
                "errors": 0,
            }

            for idx, row in enumerate(suspects, 1):
                txn_id = None
                try:
                    # Row is already a dict from sqlite3.Row
                    txn_id = row.get("txn_id")
                    user_id = row.get("user_id")

                    logger.info(f"[{idx}/{len(suspects)}] Processing {txn_id}...")

                    # Safe parse rules_triggered
                    rules_triggered = self._safe_parse_list(row.get("rules_triggered"))
                    
                    # Safe parse rule_details
                    rule_details = self._safe_parse_dict(row.get("rule_details"))

                    suspect = {
                        "txn_id": txn_id,
                        "user_id": user_id,
                        "rules_triggered": rules_triggered,
                        "rule_details": rule_details,
                    }

                    txn = {
                        "txn_id": row.get("txn_id"),
                        "user_id": row.get("user_id"),
                        "amount": row.get("amount"),
                        "merchant_category": row.get("merchant_category"),
                        "merchant_city": row.get("merchant_city"),
                        "timestamp": row.get("timestamp"),
                    }

                    profile = self.profiles.get(user_id)
                    prompt = _build_user_prompt(suspect, txn, profile)

                    # Call LLM with aggressive retry logic for free tier
                    decision = self._call_llm(prompt, txn_id=txn_id)

                    # Store decision
                    conn.execute(
                        """
                        INSERT INTO llm_decisions
                        (txn_id, user_id, verdict, confidence, reasoning, recommended_action, rules_triggered, rule_details, decided_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            txn_id,
                            user_id,
                            decision.get("verdict", "REVIEW"),
                            decision.get("confidence", 0.5),
                            decision.get("reasoning", ""),
                            decision.get("recommended_action", "MONITOR"),
                            str(rules_triggered),
                            str(rule_details),
                            datetime.utcnow().isoformat(),
                        ),
                    )

                    # Mark as processed
                    conn.execute(
                        "UPDATE suspect_queue SET llm_processed = 1 WHERE txn_id = ?",
                        (txn_id,),
                    )

                    stats["processed"] += 1
                    verdict_key = decision.get("verdict", "review").lower()
                    if verdict_key in stats:
                        stats[verdict_key] += 1

                    logger.info(f"✅ {txn_id} → {decision.get('verdict')} (confidence: {decision.get('confidence')})")

                except Exception as e:
                    stats["errors"] += 1
                    logger.error(f"❌ Failed to process {txn_id}: {e}")
                    continue

            conn.commit()
            logger.info(f"✅ Batch complete: {stats}")
            return stats

        except Exception as e:
            logger.error(f"❌ Batch processing failed: {e}", exc_info=True)
            raise
        finally:
            conn.close()