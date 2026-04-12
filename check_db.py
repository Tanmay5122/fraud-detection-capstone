"""
Database Migration Script
Fixes the llm_decisions table schema by adding missing columns
"""

import sqlite3
import sys
from pathlib import Path

DB_PATH = "data/fraud_detection.db"

def migrate_database():
    """Add missing columns to llm_decisions table"""
    
    print("=" * 80)
    print("DATABASE MIGRATION SCRIPT")
    print("=" * 80)
    
    # Check if database exists
    if not Path(DB_PATH).exists():
        print(f"\n❌ ERROR: Database not found at {DB_PATH}")
        print("\nPlease make sure you're running this from the project root:")
        print("  cd E:\\fraud-detection-capstone")
        print("  python fix_database.py")
        sys.exit(1)
    
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10.0)
        cur = conn.cursor()
        
        # Check current columns
        print(f"\n📋 Checking {DB_PATH}...")
        cur.execute("PRAGMA table_info(llm_decisions)")
        columns = cur.fetchall()
        column_names = [col[1] for col in columns]
        
        print("\nCurrent columns:")
        for col in column_names:
            print(f"  ✅ {col}")
        
        # Check for missing columns
        missing = []
        if "rules_triggered" not in column_names:
            missing.append("rules_triggered")
        if "rule_details" not in column_names:
            missing.append("rule_details")
        
        if not missing:
            print("\n✅ All required columns exist! No migration needed.")
            conn.close()
            return True
        
        # Add missing columns
        print(f"\n⚠️  Missing columns: {', '.join(missing)}")
        print("\nAdding missing columns...")
        
        if "rules_triggered" not in column_names:
            print("  → Adding rules_triggered...")
            cur.execute("""
                ALTER TABLE llm_decisions 
                ADD COLUMN rules_triggered TEXT DEFAULT '[]'
            """)
            print("    ✅ rules_triggered added")
        
        if "rule_details" not in column_names:
            print("  → Adding rule_details...")
            cur.execute("""
                ALTER TABLE llm_decisions 
                ADD COLUMN rule_details TEXT DEFAULT '{}'
            """)
            print("    ✅ rule_details added")
        
        # Commit changes
        conn.commit()
        
        # Verify
        cur.execute("PRAGMA table_info(llm_decisions)")
        new_columns = [col[1] for col in cur.fetchall()]
        
        print("\n✅ MIGRATION COMPLETE!")
        print("\nUpdated columns:")
        for col in new_columns:
            print(f"  ✅ {col}")
        
        conn.close()
        return True
        
    except sqlite3.OperationalError as e:
        print(f"\n❌ Database error: {e}")
        if "database is locked" in str(e):
            print("\nDatabase is locked. Please:")
            print("  1. Stop the FastAPI server (Ctrl+C)")
            print("  2. Stop n8n workflow (toggle OFF)")
            print("  3. Wait 10 seconds")
            print("  4. Run this script again")
        sys.exit(1)
    
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    success = migrate_database()
    sys.exit(0 if success else 1)