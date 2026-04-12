import sqlite3
from src.config import DB_PATH

"""
Fix: Add missing columns to llm_decisions table
Run this ONCE to update your database schema
"""

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

# Check current schema
cur.execute("PRAGMA table_info(llm_decisions)")
columns = [row[1] for row in cur.fetchall()]

print("Current llm_decisions columns:")
for col in columns:
    print(f"  - {col}")

# Add missing columns if they don't exist
if "rules_triggered" not in columns:
    print("\nAdding rules_triggered column...")
    cur.execute("""
        ALTER TABLE llm_decisions 
        ADD COLUMN rules_triggered TEXT DEFAULT '[]'
    """)
    print("✅ Added rules_triggered")

if "rule_details" not in columns:
    print("Adding rule_details column...")
    cur.execute("""
        ALTER TABLE llm_decisions 
        ADD COLUMN rule_details TEXT DEFAULT '{}'
    """)
    print("✅ Added rule_details")

conn.commit()
conn.close()

print("\n✅ Database migration complete!")
print("Now you can run the LLM endpoint again.")