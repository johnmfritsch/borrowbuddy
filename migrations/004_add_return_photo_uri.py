"""
Migration 004: Add return photo URI to loans table
Created: 2025-02-02
Converts migrate_return_augmentation.py to new migration format
"""

VERSION = '004'
DESCRIPTION = 'Add return_photo_uri column to loans table'

def up(db):
    """Apply the migration"""
    # Check if column already exists (idempotent)
    cursor = db.execute('PRAGMA table_info(loans)')
    columns = [row[1] for row in cursor.fetchall()]

    if 'return_photo_uri' not in columns:
        print(f'  Adding return_photo_uri column...')
        db.execute('ALTER TABLE loans ADD COLUMN return_photo_uri TEXT')

        print(f'  Creating index...')
        db.execute('CREATE INDEX IF NOT EXISTS idx_loans_return_photo ON loans(return_photo_uri)')

        print(f'  ✓ Migration {VERSION} applied')
    else:
        print(f'  ↻ Column already exists, skipping')

def down(db):
    """Rollback the migration"""
    raise NotImplementedError("SQLite does not support DROP COLUMN")

def verify(db):
    """Verify migration was applied correctly"""
    cursor = db.execute('PRAGMA table_info(loans)')
    columns = [row[1] for row in cursor.fetchall()]
    return 'return_photo_uri' in columns
