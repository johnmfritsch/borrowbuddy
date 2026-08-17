"""
Migration 005: Add is_admin column to users table
Created: 2025-02-02
"""

VERSION = '005'
DESCRIPTION = 'Add is_admin column to users table'

def up(db):
    """Apply the migration"""
    # Check if column already exists (idempotent)
    cursor = db.execute('PRAGMA table_info(users)')
    columns = [row[1] for row in cursor.fetchall()]

    if 'is_admin' not in columns:
        print(f'  Adding is_admin column...')
        db.execute('ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0')
        print(f'  ✓ Migration {VERSION} applied')
    else:
        print(f'  ↻ Column already exists, skipping')

def down(db):
    """Rollback the migration"""
    raise NotImplementedError("SQLite does not support DROP COLUMN")

def verify(db):
    """Verify migration was applied correctly"""
    cursor = db.execute('PRAGMA table_info(users)')
    columns = [row[1] for row in cursor.fetchall()]
    return 'is_admin' in columns
