"""
Feed Simulator — Phase 3
Reads transactions from the CSV dataset and inserts them into SQLite
in batches, simulating a live banking transaction feed.

Usage:
    python -m src.feed_simulator.simulator       # runs indefinitely
    python -m src.feed_simulator.simulator --once # inserts one batch and exits
"""

import sqlite3
import pandas as pd
import time
import logging
import argparse
import os
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────────
DB_PATH = "data/fraud_detection.db"
CSV_PATH = "data/processed/transactions_clean.csv"
BATCH_SIZE = int(os.getenv("FEED_BATCH_SIZE", 10))
POLL_INTERVAL = int(os.getenv("FEED_POLL_INTERVAL_SECONDS", 30))


# ── Database setup ─────────────────────────────────────────────────────────────

def init_db(db_path: str = DB_PATH):
    """Create tables if they don't exist."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # Persistent key-value store — keeps cursor position across runs
    cur.execute("""
        CREATE TABLE IF NOT EXISTS simulator_state (
            key     TEXT PRIMARY KEY,
            value   TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            txn_id          TEXT PRIMARY KEY,
            user_id         TEXT NOT NULL,
            timestamp       TEXT NOT NULL,
            amount          REAL NOT NULL,
            currency        TEXT NOT NULL,
            merchant_category TEXT NOT NULL,
            merchant_city   TEXT NOT NULL,
            merchant_lat    REAL NOT NULL,
            merchant_lon    REAL NOT NULL,
            payment_method  TEXT NOT NULL,
            hour_of_day     INTEGER,
            day_of_week     TEXT,
            is_weekend      INTEGER,
            processed       INTEGER DEFAULT 0,
            inserted_at     TEXT DEFAULT (datetime('now'))
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS suspect_queue (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            txn_id          TEXT NOT NULL,
            user_id         TEXT NOT NULL,
            rules_triggered TEXT NOT NULL,
            rule_details    TEXT NOT NULL,
            queued_at       TEXT DEFAULT (datetime('now')),
            llm_processed   INTEGER DEFAULT 0
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS llm_decisions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            txn_id          TEXT NOT NULL,
            user_id         TEXT NOT NULL,
            verdict         TEXT NOT NULL,
            confidence      REAL NOT NULL,
            rules_triggered TEXT NOT NULL,
            reasoning       TEXT NOT NULL,
            recommended_action TEXT NOT NULL,
            processing_time_ms INTEGER,
            decided_at      TEXT DEFAULT (datetime('now'))
        )
    """)

    conn.commit()
    conn.close()
    logger.info(f"Database initialised at {db_path}")


# ── Feed simulator ─────────────────────────────────────────────────────────────

class FeedSimulator:
    """
    Reads the synthetic dataset CSV and drip-feeds rows into SQLite,
    simulating a real-time transaction stream.
    Cursor position is persisted in the DB so runs pick up where they left off.
    """

    def __init__(self, csv_path: str = CSV_PATH, db_path: str = DB_PATH):
        self.csv_path = csv_path
        self.db_path = db_path
        self._df = None
        init_db(self.db_path)                   # always create tables first
        self._cursor_idx = self._load_cursor()  # resume from last position
        self._load_dataset()

    # ── Cursor persistence ────────────────────────────────────────────────────

    def _load_cursor(self) -> int:
        """Read the last cursor position from DB, defaulting to 0."""
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT value FROM simulator_state WHERE key='cursor_idx'"
        ).fetchone()
        conn.close()
        return int(row[0]) if row else 0

    def _save_cursor(self):
        """Write the current cursor position to DB so next run resumes here."""
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT OR REPLACE INTO simulator_state (key, value) VALUES ('cursor_idx', ?)",
            (str(self._cursor_idx),)
        )
        conn.commit()
        conn.close()

    # ── Dataset ───────────────────────────────────────────────────────────────

    def _load_dataset(self):
        if not Path(self.csv_path).exists():
            raise FileNotFoundError(
                f"Dataset not found at {self.csv_path}\n"
                f"Run: python notebooks/generate_dataset.py"
            )
        self._df = pd.read_csv(self.csv_path)
        logger.info(f"Loaded {len(self._df):,} transactions from {self.csv_path}")

    # ── Core methods ──────────────────────────────────────────────────────────

    def insert_batch(self, batch_size: int = BATCH_SIZE) -> int:
        """
        Insert the next batch of transactions into SQLite.
        Wraps around to the beginning when dataset is exhausted.
        Returns number of rows inserted.
        """
        if self._df is None:
            self._load_dataset()

        total = len(self._df)
        if self._cursor_idx >= total:
            logger.info("Dataset exhausted — wrapping around to start")
            self._cursor_idx = 0

        end_idx = min(self._cursor_idx + batch_size, total)
        batch = self._df.iloc[self._cursor_idx:end_idx].copy()
        self._cursor_idx = end_idx
        self._save_cursor()  # persist so next run continues from here

        # Give rows a fresh timestamp so they look "live"
        now = datetime.now()
        batch["timestamp"] = now.isoformat()

        conn = sqlite3.connect(self.db_path)
        inserted = 0
        for _, row in batch.iterrows():
            try:
                conn.execute("""
                    INSERT OR IGNORE INTO transactions
                    (txn_id, user_id, timestamp, amount, currency,
                     merchant_category, merchant_city, merchant_lat,
                     merchant_lon, payment_method, hour_of_day,
                     day_of_week, is_weekend)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    row["txn_id"], row["user_id"], row["timestamp"],
                    row["amount"], row["currency"], row["merchant_category"],
                    row["merchant_city"], row["merchant_lat"], row["merchant_lon"],
                    row["payment_method"],
                    int(now.hour),
                    now.strftime("%A"),
                    int(now.weekday() >= 5)
                ))
                inserted += 1
            except Exception as e:
                logger.warning(f"Skipped {row['txn_id']}: {e}")

        conn.commit()
        conn.close()

        logger.info(
            f"Inserted {inserted} transactions "
            f"[{self._cursor_idx}/{total} total fed]"
        )
        return inserted

    def get_unprocessed(self, limit: int = 50) -> list[dict]:
        """Fetch unprocessed transactions from DB for the rule engine."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT * FROM transactions
            WHERE processed = 0
            ORDER BY inserted_at ASC
            LIMIT ?
        """, (limit,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def mark_processed(self, txn_ids: list[str]):
        """Mark transactions as processed after rule engine has evaluated them."""
        if not txn_ids:
            return
        conn = sqlite3.connect(self.db_path)
        placeholders = ",".join("?" * len(txn_ids))
        conn.execute(
            f"UPDATE transactions SET processed=1 WHERE txn_id IN ({placeholders})",
            txn_ids
        )
        conn.commit()
        conn.close()

    def get_next_batch(self, batch_size: int = 50) -> list[dict]:
        """
        1. Insert the next unseen batch of transactions into DB
        2. Return unprocessed transactions for the rule engine
        """
        self.insert_batch(batch_size)
        return self.get_unprocessed(limit=batch_size)

    def enqueue_suspect(self, conn, txn: dict, result):
        """Add a flagged transaction to the suspect_queue."""
        conn.execute("""
            INSERT INTO suspect_queue
            (txn_id, user_id, rules_triggered, rule_details)
            VALUES (?, ?, ?, ?)
        """, (
            txn["txn_id"],
            txn["user_id"],
            ",".join(result.rules_triggered),
            str(result.__dict__)
        ))

    def run_loop(self, batch_size: int = BATCH_SIZE, interval: int = POLL_INTERVAL):
        """Run the feed simulator continuously."""
        logger.info(f"Feed simulator started — batch={batch_size}, interval={interval}s")
        print(f"\n Feed simulator running. Inserting {batch_size} txns every {interval}s.")
        print(f" Database: {self.db_path}")
        print(f" Press Ctrl+C to stop.\n")

        try:
            while True:
                self.insert_batch(batch_size)
                time.sleep(interval)
        except KeyboardInterrupt:
            logger.info("Feed simulator stopped by user.")
            print("\n Feed simulator stopped.")


# ── CLI entry point ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    parser = argparse.ArgumentParser(description="Transaction feed simulator")
    parser.add_argument("--once", action="store_true",
                        help="Insert one batch and exit (for testing)")
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    parser.add_argument("--interval", type=int, default=POLL_INTERVAL)
    args = parser.parse_args()

    init_db()
    sim = FeedSimulator()

    if args.once:
        n = sim.insert_batch(args.batch_size)
        print(f"Inserted {n} transactions. Done.")
    else:
        sim.run_loop(args.batch_size, args.interval)