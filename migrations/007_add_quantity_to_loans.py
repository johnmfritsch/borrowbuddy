"""
Migration 007: Add quantity column to loans table
Created: 2026-02-07
"""

VERSION = '007'
DESCRIPTION = 'Add quantity column to loans table for tracking loan quantities'

def up(db):
    """Apply the migration"""
    # Check if column already exists
    cursor = db.execute("PRAGMA table_info(loans)")
    columns = [col[1] for col in cursor.fetchall()]
    
    if 'quantity' in columns:
        print(f'  ↻ quantity column already exists, skipping')
        return
    
    print(f'  Adding quantity column to loans table...')
    db.execute('ALTER TABLE loans ADD COLUMN quantity INTEGER DEFAULT 1')
    print(f'  ✓ quantity column added successfully')

def down(db):
    """Reverse the migration"""
    print(f'  ⚠ Cannot remove column in SQLite - column will remain but be unused')
    # SQLite doesn't support DROP COLUMN easily, would require table rebuild
