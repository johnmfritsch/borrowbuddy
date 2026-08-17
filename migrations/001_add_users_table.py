"""
Migration 001: Add users table and multi-user support
Created: 2025-02-02
Converts migrate_db.py to new migration format
"""

VERSION = '001'
DESCRIPTION = 'Add users table and multi-user support'

def up(db):
    """Apply the migration"""
    # Check if users table already exists
    cursor = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
    if cursor.fetchone():
        print(f'  ↻ Users table already exists, skipping')
        return

    print(f'  Creating users table...')
    db.execute('''
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            display_name TEXT
        )
    ''')

    print(f'  Adding user_id columns to existing tables...')

    # Add user_id to items
    cursor = db.execute('PRAGMA table_info(items)')
    columns = [row[1] for row in cursor.fetchall()]
    if 'user_id' not in columns:
        db.execute('ALTER TABLE items ADD COLUMN user_id INTEGER')

    # Add user_id to contacts
    cursor = db.execute('PRAGMA table_info(contacts)')
    columns = [row[1] for row in cursor.fetchall()]
    if 'user_id' not in columns:
        db.execute('ALTER TABLE contacts ADD COLUMN user_id INTEGER')

    # Add user_id to loans
    cursor = db.execute('PRAGMA table_info(loans)')
    columns = [row[1] for row in cursor.fetchall()]
    if 'user_id' not in columns:
        db.execute('ALTER TABLE loans ADD COLUMN user_id INTEGER')

    # Add user_id to borrows
    cursor = db.execute('PRAGMA table_info(borrows)')
    columns = [row[1] for row in cursor.fetchall()]
    if 'user_id' not in columns:
        db.execute('ALTER TABLE borrows ADD COLUMN user_id INTEGER')

    print(f'  ✓ Migration {VERSION} applied')

def down(db):
    """Rollback the migration"""
    raise NotImplementedError("SQLite does not support DROP TABLE with foreign keys easily")

def verify(db):
    """Verify migration was applied correctly"""
    cursor = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
    return cursor.fetchone() is not None
