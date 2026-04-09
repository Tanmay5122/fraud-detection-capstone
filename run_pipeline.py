"""
run_pipeline.py — Main entry point
Usage:
    python run_pipeline.py --once        # one batch: ingest + rules + LLM
    python run_pipeline.py --rules-only  # ingest + rules, skip LLM (fast test)
    python run_pipeline.py --llm-only    # LLM agent only (process queued suspects)
    python run_pipeline.py --report      # print DB stats and exit
    python run_pipeline.py --loop        # run continuously every 30s (dev mode)
"""

import argparse
import logging
import sqlite3
import time
from datetime import datetime

from src.config import DB_PATH
from src.feed_simulator.simulator import FeedSimulator
from src.rule_engine.engine import RuleEngine
from src.rule_engine.model import Transaction

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def dict_to_transaction(d: dict) -> Transaction:
    """Convert a raw DB dict (from get_unprocessed) into a Transaction object."""
    return Transaction(
        txn_id=d["txn_id"],
        user_id=d["user_id"],
        timestamp=datetime.fromisoformat(d["timestamp"]),
        amount=float(d["amount"]),
        currency=d["currency"],
        merchant_category=d["merchant_category"],
        merchant_city=d["merchant_city"],
        merchant_lat=float(d["merchant_lat"]),
        merchant_lon=float(d["merchant_lon"]),
        payment_method=d["payment_method"],
    )


def print_report():
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM transactions")
    total = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM suspect_queue")
    suspects = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM llm_decisions")
    decisions = cur.fetchone()[0]

    cur.execute("SELECT verdict, COUNT(*) FROM llm_decisions GROUP BY verdict")
    verdicts = dict(cur.fetchall())

    conn.close()

    flag_rate = (suspects / total * 100) if total else 0
    print("\n── Pipeline report ──────────────────────")
    print(f"  Transactions in DB : {total}")
    print(f"  Suspects queued    : {suspects}")
    print(f"  Flag rate          : {flag_rate:.1f}%")
    print(f"  LLM decisions      : {decisions}")
    if verdicts:
        for v, c in verdicts.items():
            print(f"    {v:<12}: {c}")
    print("────────────────────────────────────────\n")


def run_once(rules_only: bool = False, llm_batch: int = 20):
    sim         = FeedSimulator()
    rule_engine = RuleEngine()

    # ── Ingest + rule engine ─────────────────────────────────────────────────
    raw_transactions = sim.get_next_batch(batch_size=50)
    if not raw_transactions:
        logger.info("No new transactions to process.")
        return

    # Convert dicts → Transaction objects for the rule engine
    transactions = []
    for d in raw_transactions:
        try:
            transactions.append(dict_to_transaction(d))
        except Exception as e:
            logger.warning(f"Skipping malformed transaction {d.get('txn_id')}: {e}")

    flagged = 0
    conn = sqlite3.connect(DB_PATH)
    for txn in transactions:
        result = rule_engine.evaluate(txn)
        if result.flagged:                          # was: result.is_suspect
            sim.enqueue_suspect(conn, txn.__dict__, result)
            flagged += 1
            logger.info(f"🚨 {txn.txn_id} flagged — rules: {result.rules_triggered}")
        else:
            logger.info(f"✅ {txn.txn_id} clear")
    conn.commit()
    conn.close()

    # Mark all processed transactions so they aren't re-evaluated next run
    sim.mark_processed([txn.txn_id for txn in transactions])

    logger.info(f"Rule engine: {flagged}/{len(transactions)} flagged")

    if rules_only:
        return

    # ── LLM agent ────────────────────────────────────────────────────────────
    try:
        from src.llm_agent.agent import FraudAgent
        agent = FraudAgent()
        stats = agent.process_batch(limit=llm_batch)
        logger.info(f"LLM agent complete: {stats}")
    except Exception as e:
        logger.error(f"LLM agent failed: {e}")
        logger.info("Tip: check OPENROUTER_API_KEY in .env and run setup_check.py")


def main():
    parser = argparse.ArgumentParser(description="Fraud Detection Pipeline")
    parser.add_argument("--once",       action="store_true", help="Run one batch (rules + LLM)")
    parser.add_argument("--rules-only", action="store_true", help="Run one batch, skip LLM")
    parser.add_argument("--llm-only",   action="store_true", help="Process queued suspects with LLM only")
    parser.add_argument("--report",     action="store_true", help="Print DB stats and exit")
    parser.add_argument("--loop",       action="store_true", help="Run every 30s continuously")
    parser.add_argument("--llm-batch",  type=int, default=20, help="Max suspects per LLM batch")
    args = parser.parse_args()

    if args.report:
        print_report()
        return

    if args.llm_only:
        from src.llm_agent.agent import FraudAgent
        agent = FraudAgent()
        stats = agent.process_batch(limit=args.llm_batch)
        print(stats)
        return

    if args.once or args.rules_only:
        run_once(rules_only=args.rules_only, llm_batch=args.llm_batch)
        print_report()
        return

    if args.loop:
        logger.info("Loop mode — press Ctrl+C to stop")
        while True:
            try:
                run_once(llm_batch=args.llm_batch)
            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"Cycle error: {e}")
            time.sleep(30)
        return

    # default — same as --once
    run_once(llm_batch=args.llm_batch)
    print_report()


if __name__ == "__main__":
    main()