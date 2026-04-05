"""
Rule Engine — Phase 3
Pre-filters transactions before sending to the LLM agent.
Reduces LLM API calls by ~70% by catching obvious patterns first.

Rules:
  1. amount_threshold   — single txn > ₹10,000
  2. velocity_check     — >3 txns from same user in 10 minutes
  3. geo_anomaly        — location >500 km from user's previous txn
  4. odd_hours_large    — txn >₹5,000 between 11 PM and 4 AM
"""

import math
import logging
from datetime import datetime, timedelta
from collections import defaultdict
from src.rule_engine.model import Transaction, RuleResult

logger = logging.getLogger(__name__)

# ── Thresholds (match .env.example defaults) ──────────────────────────────────
AMOUNT_THRESHOLD = 10_000          # ₹
VELOCITY_WINDOW_MINUTES = 10
VELOCITY_MAX_TXN = 3
GEO_DISTANCE_KM = 500
ODD_HOURS_START = 23               # 11 PM
ODD_HOURS_END = 4                  # 4 AM
ODD_HOURS_MIN_AMOUNT = 5_000       # ₹


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance in km between two lat/lon points."""
    R = 6371
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


class RuleEngine:
    """
    Stateful rule engine — keeps a rolling window of recent transactions
    per user to enable velocity and geo checks.
    """

    def __init__(self):
        # user_id -> list of recent transactions (rolling window)
        self._user_history: dict[str, list[Transaction]] = defaultdict(list)
        self.stats = {"processed": 0, "flagged": 0, "rules_hit": defaultdict(int)}

    def _prune_history(self, user_id: str, before: datetime):
        """Remove transactions older than the velocity window."""
        cutoff = before - timedelta(minutes=VELOCITY_WINDOW_MINUTES)
        self._user_history[user_id] = [
            t for t in self._user_history[user_id]
            if t.timestamp >= cutoff
        ]

    # ── Individual rules ──────────────────────────────────────────────────────

    def _check_amount_threshold(self, txn: Transaction) -> tuple[bool, dict]:
        triggered = txn.amount > AMOUNT_THRESHOLD
        return triggered, {
            "amount": txn.amount,
            "threshold": AMOUNT_THRESHOLD,
            "excess": round(txn.amount - AMOUNT_THRESHOLD, 2) if triggered else 0
        }

    def _check_velocity(self, txn: Transaction) -> tuple[bool, dict]:
        recent = self._user_history[txn.user_id]
        count = len(recent)
        triggered = count >= VELOCITY_MAX_TXN
        return triggered, {
            "txn_count_in_window": count,
            "window_minutes": VELOCITY_WINDOW_MINUTES,
            "max_allowed": VELOCITY_MAX_TXN,
            "oldest_in_window": recent[0].timestamp.isoformat() if recent else None
        }

    def _check_geo_anomaly(self, txn: Transaction) -> tuple[bool, dict]:
        history = self._user_history[txn.user_id]
        if not history:
            return False, {"reason": "no prior transactions to compare"}

        prev = history[-1]
        distance = haversine_km(
            prev.merchant_lat, prev.merchant_lon,
            txn.merchant_lat, txn.merchant_lon
        )
        time_diff_minutes = (txn.timestamp - prev.timestamp).total_seconds() / 60
        triggered = distance > GEO_DISTANCE_KM

        return triggered, {
            "distance_km": round(distance, 1),
            "threshold_km": GEO_DISTANCE_KM,
            "prev_city": prev.merchant_city,
            "curr_city": txn.merchant_city,
            "time_diff_minutes": round(time_diff_minutes, 1)
        }

    def _check_odd_hours_large(self, txn: Transaction) -> tuple[bool, dict]:
        hour = txn.timestamp.hour
        is_odd = hour >= ODD_HOURS_START or hour < ODD_HOURS_END
        is_large = txn.amount >= ODD_HOURS_MIN_AMOUNT
        triggered = is_odd and is_large
        return triggered, {
            "hour": hour,
            "amount": txn.amount,
            "min_amount_for_flag": ODD_HOURS_MIN_AMOUNT,
            "odd_hours_range": f"{ODD_HOURS_START}:00 – {ODD_HOURS_END}:00"
        }

    # ── Main evaluate method ──────────────────────────────────────────────────

    def evaluate(self, txn: Transaction) -> RuleResult:
        """
        Run all rules against a transaction.
        Returns a RuleResult — flagged=True means it goes to the LLM queue.
        """
        self._prune_history(txn.user_id, txn.timestamp)

        rules_triggered = []
        rule_details = {}

        # Rule 1: amount threshold
        hit, details = self._check_amount_threshold(txn)
        if hit:
            rules_triggered.append("amount_threshold")
            rule_details["amount_threshold"] = details
            self.stats["rules_hit"]["amount_threshold"] += 1

        # Rule 2: velocity
        hit, details = self._check_velocity(txn)
        if hit:
            rules_triggered.append("velocity_check")
            rule_details["velocity_check"] = details
            self.stats["rules_hit"]["velocity_check"] += 1

        # Rule 3: geo anomaly
        hit, details = self._check_geo_anomaly(txn)
        if hit:
            rules_triggered.append("geo_anomaly")
            rule_details["geo_anomaly"] = details
            self.stats["rules_hit"]["geo_anomaly"] += 1

        # Rule 4: odd hours + large amount
        hit, details = self._check_odd_hours_large(txn)
        if hit:
            rules_triggered.append("odd_hours_large")
            rule_details["odd_hours_large"] = details
            self.stats["rules_hit"]["odd_hours_large"] += 1

        # Add to history AFTER evaluation (don't let current txn affect its own check)
        self._user_history[txn.user_id].append(txn)

        flagged = len(rules_triggered) > 0
        self.stats["processed"] += 1
        if flagged:
            self.stats["flagged"] += 1

        result = RuleResult(
            txn_id=txn.txn_id,
            user_id=txn.user_id,
            flagged=flagged,
            rules_triggered=rules_triggered,
            rule_details=rule_details,
            timestamp=txn.timestamp,
            transaction=txn
        )

        if flagged:
            logger.info(
                f"[FLAGGED] {txn.txn_id} | rules: {rules_triggered} | "
                f"amount: ₹{txn.amount:,.0f} | city: {txn.merchant_city}"
            )

        return result

    def print_stats(self):
        total = self.stats["processed"]
        flagged = self.stats["flagged"]
        rate = (flagged / total * 100) if total > 0 else 0
        print(f"\n── Rule Engine Stats ────────────────────")
        print(f"  Processed : {total:,}")
        print(f"  Flagged   : {flagged:,} ({rate:.1f}%)")
        print(f"  By rule   :")
        for rule, count in self.stats["rules_hit"].items():
            print(f"    {rule:<22} {count:>5}")
        print(f"────────────────────────────────────────\n")