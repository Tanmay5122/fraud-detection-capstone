"""
Database Diagnostic & Repair Utility
Interactive tool to diagnose and fix database issues.

Usage:
    python diagnose_db.py
"""

import sqlite3
import sys
from pathlib import Path
from datetime import datetime

DB_PATH = "data/fraud_detection.db"

class DatabaseDiagnostic:
    def __init__(self):
        self.db_path = DB_PATH
        self.issues = []
        self.warnings = []
        
    def check_database_exists(self):
        """Step 1: Check if database file exists."""
        print("\n[1] Checking database file...")
        if Path(self.db_path).exists():
            size_mb = Path(self.db_path).stat().st_size / (1024 * 1024)
            print(f"    ✓ Database exists at: {self.db_path}")
            print(f"    ✓ Size: {size_mb:.2f} MB")
            return True
        else:
            print(f"    ✗ Database file not found: {self.db_path}")
            self.issues.append("Database file missing")
            return False
    
    def check_database_readable(self):
        """Step 2: Check if database is readable."""
        print("\n[2] Checking database connectivity...")
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute("SELECT 1")
            conn.close()
            print("    ✓ Database is readable and valid")
            return True
        except Exception as e:
            print(f"    ✗ Cannot read database: {e}")
            self.issues.append(f"Database read error: {e}")
            return False
    
    def check_tables(self):
        """Step 3: Check what tables exist."""
        print("\n[3] Checking tables...")
        try:
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            tables = [row[0] for row in cur.fetchall()]
            conn.close()
            
            required = ['transactions', 'suspect_queue', 'llm_decisions']
            missing = [t for t in required if t not in tables]
            
            print(f"    Found {len(tables)} table(s):")
            for table in tables:
                status = "✓" if table in required else "⚠"
                print(f"      {status} {table}")
            
            if missing:
                print(f"\n    ✗ Missing required tables: {', '.join(missing)}")
                for t in missing:
                    self.issues.append(f"Missing table: {t}")
                return False
            else:
                print("\n    ✓ All required tables exist")
                return True
        except Exception as e:
            print(f"    ✗ Error checking tables: {e}")
            self.issues.append(f"Table check failed: {e}")
            return False
    
    def check_table_columns(self):
        """Step 4: Check llm_decisions columns."""
        print("\n[4] Checking llm_decisions table structure...")
        try:
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            
            # Check if table exists first
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='llm_decisions'")
            if not cur.fetchone():
                print("    ✗ llm_decisions table does not exist")
                return False
            
            # Get columns
            cur.execute("PRAGMA table_info(llm_decisions)")
            columns = {row[1]: row[2] for row in cur.fetchall()}
            conn.close()
            
            required_cols = ['txn_id', 'user_id', 'verdict', 'confidence', 'reasoning', 'decided_at', 'responded_at']
            missing_cols = [c for c in required_cols if c not in columns]
            
            print(f"    Found {len(columns)} column(s):")
            for col in required_cols:
                if col in columns:
                    print(f"      ✓ {col} ({columns[col]})")
                else:
                    print(f"      ✗ {col} (MISSING)")
                    self.issues.append(f"Missing column: llm_decisions.{col}")
            
            return len(missing_cols) == 0
        except Exception as e:
            print(f"    ✗ Error checking columns: {e}")
            self.issues.append(f"Column check failed: {e}")
            return False
    
    def check_table_data(self):
        """Step 5: Check row counts in tables."""
        print("\n[5] Checking table contents...")
        try:
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            
            tables = ['transactions', 'suspect_queue', 'llm_decisions']
            for table in tables:
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                count = cur.fetchone()[0]
                if count == 0:
                    print(f"    ⚠ {table}: {count} rows (empty)")
                    self.warnings.append(f"{table} is empty - no data yet")
                else:
                    print(f"    ✓ {table}: {count} rows")
            
            conn.close()
            return True
        except Exception as e:
            print(f"    ✗ Error checking data: {e}")
            return False
    
    def diagnose(self):
        """Run all diagnostics."""
        print("\n" + "=" * 70)
        print("DATABASE DIAGNOSTIC REPORT")
        print("=" * 70)
        print(f"Database: {self.db_path}")
        print(f"Timestamp: {datetime.now().isoformat()}")
        
        results = [
            self.check_database_exists(),
            self.check_database_readable(),
            self.check_tables(),
            self.check_table_columns(),
            self.check_table_data(),
        ]
        
        self.print_summary(results)
    
    def print_summary(self, results):
        """Print diagnostic summary."""
        print("\n" + "=" * 70)
        print("DIAGNOSTIC SUMMARY")
        print("=" * 70)
        
        if all(results):
            print("\n✅ DATABASE IS HEALTHY")
            print("\nYour database is properly configured.")
            print("You can proceed with:")
            print("  1. uvicorn src.rpa_bots.bot1_monitor:app --host 127.0.0.1 --port 8000 --reload")
            print("  2. Invoke-RestMethod -Uri 'http://localhost:8000/fraud-alerts?limit=5' -Method GET")
        else:
            print("\n⚠️  ISSUES DETECTED")
            if self.issues:
                print("\nCritical Issues:")
                for issue in self.issues:
                    print(f"  ✗ {issue}")
            
            if self.warnings:
                print("\nWarnings:")
                for warning in self.warnings:
                    print(f"  ⚠ {warning}")
            
            print("\n" + "=" * 70)
            print("RECOMMENDED FIXES")
            print("=" * 70)
            
            if "Database file missing" in self.issues:
                print("\n1. DATABASE FILE MISSING")
                print("   Create the database with: python fix_database.py")
            
            if any("Missing table" in issue for issue in self.issues):
                print("\n2. MISSING TABLES")
                print("   Create them with: python fix_database.py")
            
            if any("Missing column" in issue for issue in self.issues):
                print("\n3. MISSING COLUMNS")
                print("   Add them with: python fix_database.py")
            
            if any("empty" in warning for warning in self.warnings):
                print("\n4. EMPTY TABLES (Not critical)")
                print("   Data will be populated when you run:")
                print("   - POST /run-cycle")
                print("   - POST /run-llm-only")


def interactive_menu():
    """Interactive menu for user."""
    while True:
        print("\n" + "=" * 70)
        print("DATABASE DIAGNOSTIC TOOL")
        print("=" * 70)
        print("\n1. Run full diagnostic")
        print("2. Create missing tables")
        print("3. Verify schema only")
        print("4. Check row counts")
        print("5. Exit")
        
        choice = input("\nSelect option (1-5): ").strip()
        
        if choice == "1":
            diag = DatabaseDiagnostic()
            diag.diagnose()
        
        elif choice == "2":
            print("\nCreating missing tables...")
            create_missing_tables()
        
        elif choice == "3":
            print("\nVerifying schema...")
            verify_schema()
        
        elif choice == "4":
            print("\nChecking row counts...")
            check_row_counts()
        
        elif choice == "5":
            print("\nExiting...")
            break
        
        else:
            print("\nInvalid option. Please select 1-5.")


def create_missing_tables():
    """Create any missing tables."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        
        # transactions
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
        
        # suspect_queue
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
        
        # llm_decisions
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
        
        # Ensure responded_at exists
        cur.execute("PRAGMA table_info(llm_decisions)")
        columns = [row[1] for row in cur.fetchall()]
        if 'responded_at' not in columns:
            cur.execute("ALTER TABLE llm_decisions ADD COLUMN responded_at TEXT DEFAULT NULL")
        
        conn.commit()
        conn.close()
        
        print("\n✅ All tables created/verified successfully!")
        
        # Verify
        verify_schema()
    
    except Exception as e:
        print(f"\n❌ Error: {e}")


def verify_schema():
    """Verify the schema is correct."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        
        print("\nVerifying schema...")
        print("-" * 70)
        
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [row[0] for row in cur.fetchall()]
        print(f"\nTables found: {', '.join(tables)}")
        
        # Check llm_decisions specifically
        cur.execute("PRAGMA table_info(llm_decisions)")
        cols = [row[1] for row in cur.fetchall()]
        print(f"\nllm_decisions columns: {', '.join(cols)}")
        
        conn.close()
        print("\n✓ Schema verification complete")
    
    except Exception as e:
        print(f"Error: {e}")


def check_row_counts():
    """Check row counts in all tables."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        
        print("\nTable row counts:")
        print("-" * 70)
        
        for table in ['transactions', 'suspect_queue', 'llm_decisions']:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            count = cur.fetchone()[0]
            print(f"  {table}: {count} rows")
        
        conn.close()
    
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--auto":
        # Auto-fix mode
        print("Running auto-fix mode...\n")
        diag = DatabaseDiagnostic()
        diag.diagnose()
        
        if diag.issues:
            print("\n\nAttempting automatic fixes...")
            create_missing_tables()
            
            print("\n\nRe-running diagnostic...")
            diag = DatabaseDiagnostic()
            diag.diagnose()
    else:
        # Interactive mode
        try:
            interactive_menu()
        except KeyboardInterrupt:
            print("\n\nExiting...")