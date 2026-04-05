"""
Phase 2 — Synthetic Transaction Dataset Generator
Generates 10,000 realistic Indian banking transactions with labelled fraud patterns.

Usage:
    python notebooks/generate_dataset.py

Output:
    data/raw/transactions.csv          — full dataset with labels
    data/raw/ground_truth.csv          — txn_id + is_fraud + fraud_type only
    data/processed/transactions_clean.csv — feature-engineered, ready for model
"""

import pandas as pd
import numpy as np
from faker import Faker
from datetime import datetime, timedelta
import random
import os
import json
from pathlib import Path

fake = Faker("en_IN")
rng = np.random.default_rng(42)
random.seed(42)

# ── Constants ─────────────────────────────────────────────────────────────────

INDIAN_CITIES = [
    ("Mumbai", 19.0760, 72.8777),
    ("Delhi", 28.6139, 77.2090),
    ("Bengaluru", 12.9716, 77.5946),
    ("Hyderabad", 17.3850, 78.4867),
    ("Chennai", 13.0827, 80.2707),
    ("Kolkata", 22.5726, 88.3639),
    ("Pune", 18.5204, 73.8567),
    ("Ahmedabad", 23.0225, 72.5714),
    ("Jaipur", 26.9124, 75.7873),
    ("Surat", 21.1702, 72.8311),
    ("Lucknow", 26.8467, 80.9462),
    ("Kochi", 9.9312, 76.2673),
]

FOREIGN_CITIES = [
    ("Dubai", 25.2048, 55.2708),
    ("Singapore", 1.3521, 103.8198),
    ("London", 51.5074, -0.1278),
    ("New York", 40.7128, -74.0060),
    ("Hong Kong", 22.3193, 114.1694),
]

MERCHANT_CATEGORIES = {
    "groceries":      (200,   8000,   0.30),   # (min, max, frequency_weight)
    "fuel":           (500,   5000,   0.12),
    "restaurant":     (150,   3000,   0.15),
    "electronics":    (2000,  80000,  0.05),
    "clothing":       (300,   15000,  0.08),
    "travel":         (1500,  50000,  0.06),
    "medical":        (200,   20000,  0.07),
    "utility":        (500,   10000,  0.09),
    "entertainment":  (100,   2000,   0.05),
    "online_shopping":(100,   30000,  0.13),
}

PAYMENT_METHODS = ["UPI", "Debit Card", "Credit Card", "NEFT", "IMPS"]

FRAUD_TYPES = [
    "velocity_abuse",        # many txns in short time
    "geo_impossibility",     # two locations impossible to travel between
    "amount_spike",          # sudden large amount vs user history
    "odd_hours_large",       # large txn at 2-4 AM
    "foreign_transaction",   # txn in foreign city without travel history
]

N_TOTAL = 10_000
N_FRAUD = 1_500
N_NORMAL = N_TOTAL - N_FRAUD
N_USERS = 500
START_DATE = datetime(2024, 1, 1)
END_DATE = datetime(2024, 12, 31)


# ── User profiles ─────────────────────────────────────────────────────────────

def generate_users(n: int) -> dict:
    users = {}
    for i in range(n):
        uid = f"USR_{i+1:04d}"
        home_city = random.choice(INDIAN_CITIES)
        avg_spend = rng.integers(500, 15000)
        users[uid] = {
            "user_id": uid,
            "name": fake.name(),
            "home_city": home_city[0],
            "home_lat": home_city[1],
            "home_lon": home_city[2],
            "avg_monthly_spend": int(avg_spend),
            "typical_max_txn": int(avg_spend * rng.uniform(2, 5)),
            "account_age_days": int(rng.integers(30, 3650)),
        }
    return users


# ── Helper functions ──────────────────────────────────────────────────────────

def haversine_km(lat1, lon1, lat2, lon2) -> float:
    R = 6371
    phi1, phi2 = np.radians(lat1), np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlambda = np.radians(lon2 - lon1)
    a = np.sin(dphi/2)**2 + np.cos(phi1)*np.cos(phi2)*np.sin(dlambda/2)**2
    return 2 * R * np.arcsin(np.sqrt(a))


def random_timestamp(start: datetime, end: datetime) -> datetime:
    delta = end - start
    return start + timedelta(seconds=int(rng.integers(0, int(delta.total_seconds()))))


def pick_merchant_category() -> str:
    cats = list(MERCHANT_CATEGORIES.keys())
    weights = [MERCHANT_CATEGORIES[c][2] for c in cats]
    return random.choices(cats, weights=weights, k=1)[0]


def normal_amount(category: str) -> float:
    lo, hi, _ = MERCHANT_CATEGORIES[category]
    return round(float(rng.uniform(lo, hi)), 2)


# ── Normal transaction factory ────────────────────────────────────────────────

def make_normal_txn(txn_id: str, user: dict, ts: datetime) -> dict:
    city = random.choice(INDIAN_CITIES)
    category = pick_merchant_category()
    return {
        "txn_id": txn_id,
        "user_id": user["user_id"],
        "timestamp": ts.isoformat(),
        "amount": normal_amount(category),
        "currency": "INR",
        "merchant_category": category,
        "merchant_city": city[0],
        "merchant_lat": city[1],
        "merchant_lon": city[2],
        "payment_method": random.choice(PAYMENT_METHODS),
        "is_fraud": 0,
        "fraud_type": "none",
        "fraud_note": "",
    }


# ── Fraud pattern factories ───────────────────────────────────────────────────

def make_velocity_abuse(base_id: int, user: dict, anchor_ts: datetime) -> list:
    """5–7 transactions within 8 minutes from the same user."""
    records = []
    n = random.randint(5, 7)
    city = random.choice(INDIAN_CITIES)
    for i in range(n):
        ts = anchor_ts + timedelta(seconds=random.randint(0, 480))
        records.append({
            "txn_id": f"TXN_F{base_id:05d}_{i}",
            "user_id": user["user_id"],
            "timestamp": ts.isoformat(),
            "amount": round(float(rng.uniform(500, 3000)), 2),
            "currency": "INR",
            "merchant_category": "online_shopping",
            "merchant_city": city[0],
            "merchant_lat": city[1],
            "merchant_lon": city[2],
            "payment_method": "Credit Card",
            "is_fraud": 1,
            "fraud_type": "velocity_abuse",
            "fraud_note": f"Txn {i+1} of {n} within 8-min window",
        })
    return records


def make_geo_impossibility(base_id: int, user: dict, anchor_ts: datetime) -> list:
    """Two transactions in cities 1500+ km apart within 30 minutes."""
    city1 = random.choice(INDIAN_CITIES)
    city2 = random.choice(FOREIGN_CITIES)
    ts2 = anchor_ts + timedelta(minutes=random.randint(15, 30))
    dist = haversine_km(city1[1], city1[2], city2[1], city2[2])
    return [
        {
            "txn_id": f"TXN_F{base_id:05d}_A",
            "user_id": user["user_id"],
            "timestamp": anchor_ts.isoformat(),
            "amount": round(float(rng.uniform(1000, 8000)), 2),
            "currency": "INR",
            "merchant_category": pick_merchant_category(),
            "merchant_city": city1[0],
            "merchant_lat": city1[1],
            "merchant_lon": city1[2],
            "payment_method": random.choice(PAYMENT_METHODS),
            "is_fraud": 1,
            "fraud_type": "geo_impossibility",
            "fraud_note": f"Pair A — {dist:.0f} km from next txn in {int((ts2-anchor_ts).seconds/60)} min",
        },
        {
            "txn_id": f"TXN_F{base_id:05d}_B",
            "user_id": user["user_id"],
            "timestamp": ts2.isoformat(),
            "amount": round(float(rng.uniform(1000, 8000)), 2),
            "currency": "USD" if city2 in FOREIGN_CITIES else "INR",
            "merchant_category": pick_merchant_category(),
            "merchant_city": city2[0],
            "merchant_lat": city2[1],
            "merchant_lon": city2[2],
            "payment_method": "Credit Card",
            "is_fraud": 1,
            "fraud_type": "geo_impossibility",
            "fraud_note": f"Pair B — {dist:.0f} km from prior txn in {int((ts2-anchor_ts).seconds/60)} min",
        },
    ]


def make_amount_spike(base_id: int, user: dict, anchor_ts: datetime) -> list:
    """Single txn 10–20x the user's typical max."""
    spike = round(user["typical_max_txn"] * random.uniform(10, 20), 2)
    city = random.choice(INDIAN_CITIES)
    return [{
        "txn_id": f"TXN_F{base_id:05d}",
        "user_id": user["user_id"],
        "timestamp": anchor_ts.isoformat(),
        "amount": spike,
        "currency": "INR",
        "merchant_category": random.choice(["electronics", "travel", "online_shopping"]),
        "merchant_city": city[0],
        "merchant_lat": city[1],
        "merchant_lon": city[2],
        "payment_method": "Credit Card",
        "is_fraud": 1,
        "fraud_type": "amount_spike",
        "fraud_note": f"Spike ₹{spike:,.0f} vs typical max ₹{user['typical_max_txn']:,}",
    }]


def make_odd_hours_large(base_id: int, user: dict, anchor_ts: datetime) -> list:
    """Large txn between 2–4 AM."""
    ts = anchor_ts.replace(hour=random.randint(2, 4), minute=random.randint(0, 59))
    amount = round(float(rng.uniform(15000, 80000)), 2)
    city = random.choice(INDIAN_CITIES)
    return [{
        "txn_id": f"TXN_F{base_id:05d}",
        "user_id": user["user_id"],
        "timestamp": ts.isoformat(),
        "amount": amount,
        "currency": "INR",
        "merchant_category": random.choice(["electronics", "online_shopping", "travel"]),
        "merchant_city": city[0],
        "merchant_lat": city[1],
        "merchant_lon": city[2],
        "payment_method": random.choice(["Credit Card", "Debit Card"]),
        "is_fraud": 1,
        "fraud_type": "odd_hours_large",
        "fraud_note": f"₹{amount:,.0f} at {ts.strftime('%H:%M')}",
    }]


def make_foreign_transaction(base_id: int, user: dict, anchor_ts: datetime) -> list:
    """Txn in foreign city with no prior travel history."""
    city = random.choice(FOREIGN_CITIES)
    amount = round(float(rng.uniform(5000, 50000)), 2)
    return [{
        "txn_id": f"TXN_F{base_id:05d}",
        "user_id": user["user_id"],
        "timestamp": anchor_ts.isoformat(),
        "amount": amount,
        "currency": "USD",
        "merchant_category": random.choice(["travel", "electronics", "restaurant"]),
        "merchant_city": city[0],
        "merchant_lat": city[1],
        "merchant_lon": city[2],
        "payment_method": "Credit Card",
        "is_fraud": 1,
        "fraud_type": "foreign_transaction",
        "fraud_note": f"Foreign txn in {city[0]}, home city: {user['home_city']}",
    }]


FRAUD_FACTORIES = {
    "velocity_abuse":     make_velocity_abuse,
    "geo_impossibility":  make_geo_impossibility,
    "amount_spike":       make_amount_spike,
    "odd_hours_large":    make_odd_hours_large,
    "foreign_transaction":make_foreign_transaction,
}

# Approx how many raw rows each pattern produces (for budget planning)
FRAUD_PATTERN_SIZES = {
    "velocity_abuse": 6,
    "geo_impossibility": 2,
    "amount_spike": 1,
    "odd_hours_large": 1,
    "foreign_transaction": 1,
}


# ── Main generator ────────────────────────────────────────────────────────────

def generate_dataset():
    print("Generating user profiles...")
    users = generate_users(N_USERS)
    user_list = list(users.values())

    # ── Normal transactions ───────────────────────────────────────────────────
    print(f"Generating {N_NORMAL} normal transactions...")
    normal_txns = []
    for i in range(N_NORMAL):
        user = random.choice(user_list)
        ts = random_timestamp(START_DATE, END_DATE)
        txn = make_normal_txn(f"TXN_N{i+1:05d}", user, ts)
        normal_txns.append(txn)

    # ── Fraud transactions ────────────────────────────────────────────────────
    print(f"Generating ~{N_FRAUD} fraud transactions across 5 patterns...")

    # Distribute 1500 fraud rows across 5 patterns evenly
    pattern_counts = {p: 300 for p in FRAUD_TYPES}   # 300 rows each = 1500 total
    # Velocity abuse produces ~6 rows per instance → ~50 instances
    # Geo impossibility produces 2 rows → ~150 instances
    # Others produce 1 row → 300 instances each

    fraud_txns = []
    fraud_id = 1

    for pattern, target_rows in pattern_counts.items():
        rows_per_call = FRAUD_PATTERN_SIZES[pattern]
        instances = max(1, target_rows // rows_per_call)
        factory = FRAUD_FACTORIES[pattern]
        for _ in range(instances):
            user = random.choice(user_list)
            ts = random_timestamp(START_DATE, END_DATE)
            rows = factory(fraud_id, user, ts)
            fraud_txns.extend(rows)
            fraud_id += 1

    # ── Combine, shuffle, save ────────────────────────────────────────────────
    print("Combining and saving...")
    all_txns = normal_txns + fraud_txns
    df = pd.DataFrame(all_txns)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sample(frac=1, random_state=42).reset_index(drop=True)

    # Add engineered features useful for the rule engine and LLM context
    df["hour_of_day"] = df["timestamp"].dt.hour
    df["day_of_week"] = df["timestamp"].dt.day_name()
    df["is_weekend"] = df["timestamp"].dt.dayofweek >= 5
    df["amount_rounded"] = (df["amount"] % 100 == 0).astype(int)  # suspiciously round amounts

    # Save full dataset
    Path("data/raw").mkdir(parents=True, exist_ok=True)
    Path("data/processed").mkdir(parents=True, exist_ok=True)

    df.to_csv("data/raw/transactions.csv", index=False)
    print(f"  Saved data/raw/transactions.csv — {len(df):,} rows")

    # Ground truth (for evaluation chapter — never feed to LLM)
    gt = df[["txn_id", "is_fraud", "fraud_type"]].copy()
    gt.to_csv("data/raw/ground_truth.csv", index=False)
    print(f"  Saved data/raw/ground_truth.csv — {len(gt):,} rows")

    # Clean version (no labels — what the pipeline actually sees)
    clean_cols = [c for c in df.columns if c not in ["is_fraud", "fraud_type", "fraud_note"]]
    df[clean_cols].to_csv("data/processed/transactions_clean.csv", index=False)
    print(f"  Saved data/processed/transactions_clean.csv")

    # Save user profiles (needed by LLM agent for context)
    with open("data/raw/user_profiles.json", "w") as f:
        json.dump(users, f, indent=2)
    print(f"  Saved data/raw/user_profiles.json — {len(users)} users")

    # ── Summary stats ─────────────────────────────────────────────────────────
    print("\n── Dataset Summary ──────────────────────────────────────────────")
    print(f"  Total transactions : {len(df):,}")
    print(f"  Normal             : {(df.is_fraud == 0).sum():,} ({(df.is_fraud==0).mean()*100:.1f}%)")
    print(f"  Fraudulent         : {(df.is_fraud == 1).sum():,} ({(df.is_fraud==1).mean()*100:.1f}%)")
    print(f"\n  Fraud by pattern:")
    for pt in FRAUD_TYPES:
        n = (df.fraud_type == pt).sum()
        print(f"    {pt:<25} {n:>5} rows")
    print(f"\n  Amount range       : ₹{df.amount.min():,.2f} – ₹{df.amount.max():,.2f}")
    print(f"  Median amount      : ₹{df.amount.median():,.2f}")
    print(f"  Date range         : {df.timestamp.min().date()} → {df.timestamp.max().date()}")
    print("─────────────────────────────────────────────────────────────────\n")
    print("✅ Dataset generation complete. Run the EDA notebook next.")

    return df


if __name__ == "__main__":
    generate_dataset()