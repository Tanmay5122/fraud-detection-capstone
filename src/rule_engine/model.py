"""
Data models shared across the pipeline.
All modules import Transaction and RuleResult from here.
"""

from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime


# ─────────────────────────────────────────────────────────────────────────────
# TRANSACTION MODEL
# ─────────────────────────────────────────────────────────────────────────────
class Transaction(BaseModel):
    txn_id: str
    user_id: str
    timestamp: datetime
    amount: float
    currency: str
    merchant_category: str
    merchant_city: str
    merchant_lat: float
    merchant_lon: float
    payment_method: str

    # Derived features
    hour_of_day: Optional[int] = None
    day_of_week: Optional[str] = None
    is_weekend: Optional[bool] = None

    # ─────────────────────────────────────────────────────────────────────────
    # AUTO-FEATURE ENGINEERING
    # ─────────────────────────────────────────────────────────────────────────
    def model_post_init(self, __context):
        if self.timestamp:
            if self.hour_of_day is None:
                self.hour_of_day = self.timestamp.hour

            if self.day_of_week is None:
                self.day_of_week = self.timestamp.strftime("%A")

            if self.is_weekend is None:
                self.is_weekend = self.timestamp.weekday() >= 5

    # ─────────────────────────────────────────────────────────────────────────
    # SAFE CONSTRUCTOR FROM ANY INPUT
    # ─────────────────────────────────────────────────────────────────────────
    @classmethod
    def from_any(cls, txn, columns=None):
        """
        Accept dict input → return Transaction
        """
        if isinstance(txn, dict):
            d = txn
        elif isinstance(txn, tuple):
            if columns is None:
                raise ValueError("Columns required for tuple conversion")
            d = dict(zip(columns, txn))
        else:
            raise TypeError(f"Unsupported type: {type(txn)}")

        try:
            # Ensure proper type casting
            d["amount"] = float(d.get("amount", 0))
            d["merchant_lat"] = float(d.get("merchant_lat", 0))
            d["merchant_lon"] = float(d.get("merchant_lon", 0))

            if isinstance(d.get("timestamp"), str):
                d["timestamp"] = datetime.fromisoformat(d["timestamp"])

            return cls(**d)

        except Exception as e:
            raise ValueError(f"Transaction creation failed: {d}") from e


# ─────────────────────────────────────────────────────────────────────────────
# RULE RESULT MODEL
# ─────────────────────────────────────────────────────────────────────────────
class RuleResult(BaseModel):
    txn_id: str
    user_id: str
    flagged: bool
    rules_triggered: List[str]
    rule_details: Dict[str, Any]
    timestamp: datetime
    transaction: Optional[Transaction] = None