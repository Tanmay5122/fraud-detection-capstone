"""
Data models shared across the pipeline.
All modules import Transaction and RuleResult from here.
"""
from pydantic import BaseModel
from typing import Optional
from datetime import datetime


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
    hour_of_day: Optional[int] = None
    day_of_week: Optional[str] = None
    is_weekend: Optional[bool] = None

    def model_post_init(self, __context):
        if self.hour_of_day is None:
            self.hour_of_day = self.timestamp.hour
        if self.day_of_week is None:
            self.day_of_week = self.timestamp.strftime("%A")
        if self.is_weekend is None:
            self.is_weekend = self.timestamp.weekday() >= 5


class RuleResult(BaseModel):
    txn_id: str
    user_id: str
    flagged: bool
    rules_triggered: list[str]
    rule_details: dict
    timestamp: datetime
    transaction: Transaction