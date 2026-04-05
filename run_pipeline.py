"""
run_pipeline.py — Phase 3 entry point
Runs the full feed → rule engine loop.

Usage:
    python run_pipeline.py              # runs continuously
    python run_pipeline.py --once       # one cycle, then exit (good for testing)
    python run_pipeline.py --report     # print rule engine stats and exit
"""

import time
import json
import logging
import argparse
import sqlite3
from datetime import datetime
from pathlib import Path

from src.feed_simulator.simulator import FeedSimulator, init_db, DB_PATH
from src.rule_engine.engine import RuleEngine
from src.rule_engine.model import Transaction

# ── Logging ───────────────────────────────────────────────────────────────────
Path("logs").mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(f"logs/pipeline_{datetime.now().strftime('%Y%m%d')}.log")
    ]
)
logger = logging.getLogger(__name__)


def write_to_suspect_queue(rule_result, db_path: str = DB_PATH):
    """Write a flagged transaction to the suspect queue for the LLM agent."""
    conn = sqlite3.connect(db_path)
    conn.execute("""
        INSERT OR IGNORE INTO suspect_queue
        (txn_id, user_id, rules_triggered, rule_details)
        VALUES (?, ?, ?, ?)
    """, (
        rule_result.txn_id,
        rule_result.user_id,
        json.dumps(rule_result.rules_triggered),
        json.dumps(rule_result.rule_details)
    ))
    conn.commit()
    conn.close()


def run_cycle(simulator: FeedSimulator, engine: RuleEngine) -> dict:
    """
    One full cycle:
      1. Insert a fresh batch into the DB
      2. Fetch all unprocessed transactions
      3. Run rule engine on each
      4. Write suspects to queue
      5. Mark all as processed
    Returns cycle stats.
    """
    # Step 1: insert new transactions
    simulator.insert_batch()

    # Step 2: fetch unprocessed
    raw_txns = simulator.get_unprocessed(limit=100)
    if not raw_txns:
        logger.info("No unprocessed transactions found.")
        return {"evaluated": 0, "flagged": 0}

    evaluated = 0
    flagged = 0
    txn_ids = []

    for row in raw_txns:
        try:
            txn = Transaction(
                txn_id=row["txn_id"],
                user_id=row["user_id"],
                timestamp=row["timestamp"],
                amount=float(row["amount"]),
                currency=row["currency"],
                merchant_category=row["merchant_category"],
                merchant_city=row["merchant_city"],
                merchant_lat=float(row["merchant_lat"]),
                merchant_lon=float(row["merchant_lon"]),
                payment_method=row["payment_method"],
            )

            result = engine.evaluate(txn)
            evaluated += 1
            txn_ids.append(txn.txn_id)

            if result.flagged:
                write_to_suspect_queue(result)
                flagged += 1
                print(
                    f"  🚨 FLAGGED  {txn.txn_id} | "
                    f"₹{txn.amount:>10,.0f} | "
                    f"{txn.merchant_city:<12} | "
                    f"rules: {result.rules_triggered}"
                )
            else:
                print(
                    f"  ✅ CLEAR    {txn.txn_id} | "
                    f"₹{txn.amount:>10,.0f} | "
                    f"{txn.merchant_city}"
                )

        except Exception as e:
            logger.warning(f"Error processing {row.get('txn_id', '?')}: {e}")

    # Step 5: mark all as processed
    simulator.mark_processed(txn_ids)

    return {"evaluated": evaluated, "flagged": flagged}


def run_once(simulator: FeedSimulator, engine: RuleEngine):
    """Single cycle — useful for testing."""
    print("\n── Single cycle run ─────────────────────────────────────────────\n")
    stats = run_cycle(simulator, engine)
    print(f"\n── Cycle complete: {stats['evaluated']} evaluated, {stats['flagged']} flagged ──")
    engine.print_stats()

    # Show suspect queue
    conn = sqlite3.connect(DB_PATH)
    queue = conn.execute(
        "SELECT txn_id, rules_triggered, queued_at FROM suspect_queue ORDER BY queued_at DESC LIMIT 10"
    ).fetchall()
    conn.close()

    if queue:
        print(f"\n── Suspect queue (latest 10) ────────────────────────────────────")
        for row in queue:
            print(f"  {row[0]}  rules: {row[1]}  queued: {row[2]}")
        print()
    else:
        print("\n  Suspect queue is empty.\n")


def run_continuous(simulator: FeedSimulator, engine: RuleEngine, interval: int = 30):
    """Continuous loop — the actual Phase 3 pipeline."""
    print(f"\n Pipeline running. Cycle every {interval}s. Press Ctrl+C to stop.\n")
    cycle = 0
    try:
        while True:
            cycle += 1
            print(f"\n{'─'*60}")
            print(f" Cycle #{cycle}  {datetime.now().strftime('%H:%M:%S')}")
            print(f"{'─'*60}")
            stats = run_cycle(simulator, engine)
            print(f"\n  Cycle #{cycle} done — {stats['evaluated']} evaluated, {stats['flagged']} flagged")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n\n Pipeline stopped.")
        engine.print_stats()


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fraud detection pipeline")
    parser.add_argument("--once", action="store_true",
                        help="Run one cycle and exit")
    parser.add_argument("--interval", type=int, default=30,
                        help="Seconds between cycles (default: 30)")
    parser.add_argument("--report", action="store_true",
                        help="Print rule engine stats from DB and exit")
    args = parser.parse_args()

    # Initialise DB
    init_db()

    if args.report:
        conn = sqlite3.connect(DB_PATH)
        total = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        flagged = conn.execute("SELECT COUNT(*) FROM suspect_queue").fetchone()[0]
        conn.close()
        print(f"\n── Pipeline report ──────────────────────")
        print(f"  Transactions in DB : {total:,}")
        print(f"  Suspects queued    : {flagged:,}")
        print(f"  Flag rate          : {flagged/total*100:.1f}%" if total > 0 else "  No data yet")
        print(f"────────────────────────────────────────\n")
    else:
        simulator = FeedSimulator()
        engine = RuleEngine()

        if args.once:
            run_once(simulator, engine)
        else:
            run_continuous(simulator, engine, interval=args.interval)