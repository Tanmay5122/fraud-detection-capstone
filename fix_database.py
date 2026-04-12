"""
Database Diagnostic & Schema Fix Script
Checks for missing tables and creates them if needed.

Usage:
    python fix_database.py
"""

import sqlite3
import sys
from pathlib import Path
from datetime import datetime

# Adjust this path to match your actual DB_PATH from config
DB_PATH = "data/fraud_detection.db"

def check_tables():
    """Check what tables exist in the database."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        
        # Get all table names
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        existing_tables = [row[0] for row in cur.fetchall()]
        
        conn.close()
        
        print("=" * 70)
        print("DATABASE SCHEMA CHECK")
        print("=" * 70)
        print(f"\nDatabase path: {DB_PATH}")
        print(f"\nExisting tables ({len(existing_tables)}):")
        
        required_tables = ['transactions', 'suspect_queue', 'llm_decisions']
        
        for table in required_tables:
            status = "✓" if table in existing_tables else "✗"
            print(f"  {status} {table}")
        
        if existing_tables:
            print(f"\nOther tables: {', '.join([t for t in existing_tables if t not in required_tables])}")
        
        missing = [t for t in required_tables if t not in existing_tables]
        return missing
    
    except Exception as e:
        print(f"❌ Error checking database: {e}")
        return None


def create_missing_tables():
    """Create the missing tables with proper schema."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        
        print("\n" + "=" * 70)
        print("CREATING MISSING TABLES")
        print("=" * 70)
        
        # Table 1: transactions (raw feed data)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                txn_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                amount REAL NOT NULL,
                currency TEXT DEFAULT 'INR',
                merchant_category TEXT,
                merchant_city TEXT,
                merchant_lat REAL,
                merchant_lon REAL,
                payment_method TEXT,
                processed INTEGER DEFAULT 0,
                ingested_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        print("✓ Created: transactions")
        
        # Table 2: suspect_queue (rule engine output)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS suspect_queue (
                queue_id INTEGER PRIMARY KEY AUTOINCREMENT,
                txn_id TEXT UNIQUE NOT NULL,
                user_id TEXT NOT NULL,
                amount REAL NOT NULL,
                risk_score REAL,
                rules_triggered TEXT,
                flagged_rules_count INTEGER DEFAULT 0,
                llm_processed INTEGER DEFAULT 0,
                queued_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(txn_id) REFERENCES transactions(txn_id)
            )
        """)
        print("✓ Created: suspect_queue")
        
        # Table 3: llm_decisions (LLM agent output) - THE KEY TABLE!
        cur.execute("""
            CREATE TABLE IF NOT EXISTS llm_decisions (
                decision_id INTEGER PRIMARY KEY AUTOINCREMENT,
                txn_id TEXT UNIQUE NOT NULL,
                user_id TEXT NOT NULL,
                amount REAL,
                verdict TEXT NOT NULL,
                confidence REAL DEFAULT 0.0,
                reasoning TEXT,
                recommended_action TEXT,
                decided_at TEXT DEFAULT CURRENT_TIMESTAMP,
                responded_at TEXT DEFAULT NULL,
                FOREIGN KEY(txn_id) REFERENCES transactions(txn_id)
            )
        """)
        print("✓ Created: llm_decisions")
        
        # Add responded_at column if it doesn't exist
        cur.execute("PRAGMA table_info(llm_decisions)")
        columns = [col[1] for col in cur.fetchall()]
        
        if 'responded_at' not in columns:
            cur.execute("ALTER TABLE llm_decisions ADD COLUMN responded_at TEXT DEFAULT NULL")
            print("✓ Added column: llm_decisions.responded_at")
        
        conn.commit()
        conn.close()
        
        print("\n✅ All tables created successfully!")
        return True
    
    except Exception as e:
        print(f"❌ Error creating tables: {e}")
        return False


def verify_schema():
    """Verify the schema is correct."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        
        print("\n" + "=" * 70)
        print("SCHEMA VERIFICATION")
        print("=" * 70)
        
        # Check llm_decisions table columns
        cur.execute("PRAGMA table_info(llm_decisions)")
        columns = cur.fetchall()
        
        print("\nllm_decisions table columns:")
        required_cols = ['txn_id', 'user_id', 'verdict', 'confidence', 'reasoning', 'decided_at', 'responded_at']
        
        found_cols = [col[1] for col in columns]
        
        for col in required_cols:
            status = "✓" if col in found_cols else "✗"
            print(f"  {status} {col}")
        
        # Count rows
        cur.execute("SELECT COUNT(*) FROM llm_decisions")
        count = cur.fetchone()[0]
        print(f"\nCurrent rows in llm_decisions: {count}")
        
        conn.close()
        
        print("\n✅ Schema verification complete!")
        return True
    
    except Exception as e:
        print(f"❌ Error verifying schema: {e}")
        return False


def main():
    print("\n🔍 Checking fraud detection database...\n")
    
    # Check what's missing
    missing = check_tables()
    
    if missing is None:
        print("\n❌ Cannot connect to database. Check DB_PATH and ensure database exists.")
        sys.exit(1)
    
    if not missing:
        print("\n✅ All required tables exist!")
        verify_schema()
        return
    
    print(f"\n⚠️  Missing tables: {', '.join(missing)}")
    print("\nAttempting to create missing tables...")
    
    if create_missing_tables():
        verify_schema()
        print("\n" + "=" * 70)
        print("✅ DATABASE FIX COMPLETE")
        print("=" * 70)
        print("\nYou can now run:")
        print("  uvicorn src.rpa_bots.bot1_monitor:app --host 127.0.0.1 --port 8000 --reload")
        print("\nAnd test:")
        print("  Invoke-RestMethod -Uri 'http://localhost:8000/fraud-alerts?limit=5' -Method GET")
    else:
        print("\n❌ Failed to create tables.")
        sys.exit(1)


if __name__ == "__main__":
    main()