"""
Migration 003: Add email and phone to contacts
Created: 2025-02-02
Converts migrate_contacts.py to new migration format
"""

VERSION = '003'
DESCRIPTION = 'Add email and phone to contacts'

def up(db):
    """Apply the migration"""
    print(f'  Adding contact fields...')

    # Add email column
    cursor = db.execute('PRAGMA table_info(contacts)')
    columns = [row[1] for row in cursor.fetchall()]
    if 'email' not in columns:
        db.execute('ALTER TABLE contacts ADD COLUMN email TEXT')
        print(f'    Added email column')
    else:
        print(f'    ↻ email column already exists')

    # Add phone column
    cursor = db.execute('PRAGMA table_info(contacts)')
    columns = [row[1] for row in cursor.fetchall()]
    if 'phone' not in columns:
        db.execute('ALTER TABLE contacts ADD COLUMN phone TEXT')
        print(f'    Added phone column')
    else:
        print(f'    ↻ phone column already exists')

    print(f'  Creating index for duplicate detection...')
    db.execute('CREATE INDEX IF NOT EXISTS idx_contacts_name_user ON contacts(name, user_id)')

    print(f'  ✓ Migration {VERSION} applied')

def down(db):
    """Rollback the migration"""
    raise NotImplementedError("SQLite does not support DROP COLUMN")

def verify(db):
    """Verify migration was applied correctly"""
    cursor = db.execute('PRAGMA table_info(contacts)')
    columns = [row[1] for row in cursor.fetchall()]
    return 'email' in columns and 'phone' in columns
