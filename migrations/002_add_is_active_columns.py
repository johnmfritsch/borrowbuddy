"""
Migration 002: Add is_active columns for soft delete
Created: 2025-02-02
Converts migrate_management.py to new migration format
"""

VERSION = '002'
DESCRIPTION = 'Add is_active columns for soft delete'

def up(db):
    """Apply the migration"""
    print(f'  Adding is_active columns...')

    # Add is_active to contacts
    cursor = db.execute('PRAGMA table_info(contacts)')
    columns = [row[1] for row in cursor.fetchall()]
    if 'is_active' not in columns:
        db.execute('ALTER TABLE contacts ADD COLUMN is_active INTEGER DEFAULT 1')
        print(f'    Added is_active to contacts')
    else:
        print(f'    ↻ contacts.is_active already exists')

    # Add is_active to items
    cursor = db.execute('PRAGMA table_info(items)')
    columns = [row[1] for row in cursor.fetchall()]
    if 'is_active' not in columns:
        db.execute('ALTER TABLE items ADD COLUMN is_active INTEGER DEFAULT 1')
        print(f'    Added is_active to items')
    else:
        print(f'    ↻ items.is_active already exists')

    print(f'  Creating indexes...')
    db.execute('CREATE INDEX IF NOT EXISTS idx_contacts_active ON contacts(is_active)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_items_active ON items(is_active)')

    print(f'  ✓ Migration {VERSION} applied')

def down(db):
    """Rollback the migration"""
    raise NotImplementedError("SQLite does not support DROP COLUMN")

def verify(db):
    """Verify migration was applied correctly"""
    cursor = db.execute('PRAGMA table_info(items)')
    columns = [row[1] for row in cursor.fetchall()]
    return 'is_active' in columns
