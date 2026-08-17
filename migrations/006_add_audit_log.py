"""
Migration 006: Add audit log table
Created: 2026-02-02
"""

VERSION = '006'
DESCRIPTION = 'Add audit log table for tracking user activity'

def up(db):
    """Apply the migration"""
    # Check if table already exists
    cursor = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='audit_log'")
    if cursor.fetchone():
        print(f'  ↻ audit_log table already exists, skipping')
        return

    print(f'  Creating audit_log table...')
    db.execute('''
        CREATE TABLE audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            user_email TEXT NOT NULL,
            action TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id INTEGER,
            entity_name TEXT,
            details TEXT,
            ip_address TEXT,
            timestamp TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')

    print(f'  Creating indexes...')
    db.execute('CREATE INDEX idx_audit_user ON audit_log(user_id)')
    db.execute('CREATE INDEX idx_audit_timestamp ON audit_log(timestamp)')
    db.execute('CREATE INDEX idx_audit_action ON audit_log(action)')
    db.execute('CREATE INDEX idx_audit_entity ON audit_log(entity_type)')

    print(f'  ✓ Migration {VERSION} applied')

def down(db):
    """Rollback the migration"""
    raise NotImplementedError("Cannot rollback audit log table creation")

def verify(db):
    """Verify migration was applied correctly"""
    cursor = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='audit_log'")
    return cursor.fetchone() is not None
