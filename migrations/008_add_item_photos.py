"""
Migration 008: Add item_photos table for multiple photos per item
Created: 2026-02-07
"""

VERSION = '008'
DESCRIPTION = 'Add item_photos table for multiple photos per item'

def up(db):
    """Apply the migration"""
    # Check if table already exists
    cursor = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='item_photos'")
    if cursor.fetchone():
        print('  item_photos table already exists, skipping creation')
    else:
        print('  Creating item_photos table...')
        db.execute('''
            CREATE TABLE item_photos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id INTEGER NOT NULL,
                photo_uri TEXT NOT NULL,
                filename TEXT NOT NULL,
                is_default INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                FOREIGN KEY (item_id) REFERENCES items(id)
            )
        ''')
        db.execute('CREATE INDEX IF NOT EXISTS idx_item_photos_item_id ON item_photos(item_id)')
        print('  item_photos table created successfully')

    # Migrate existing photos from items.photo_uri
    rows = db.execute("""
        SELECT id, photo_uri, user_id FROM items
        WHERE photo_uri IS NOT NULL AND photo_uri != ''
    """).fetchall()

    migrated = 0
    for row in rows:
        # Check if already migrated
        existing = db.execute(
            'SELECT id FROM item_photos WHERE item_id = ? AND photo_uri = ?',
            (row['id'], row['photo_uri'])
        ).fetchone()
        if existing:
            continue

        # Extract filename from URI
        photo_uri = row['photo_uri']
        filename = photo_uri.rsplit('/', 1)[-1] if '/' in photo_uri else photo_uri

        db.execute('''
            INSERT INTO item_photos (item_id, photo_uri, filename, is_default, created_at, user_id)
            VALUES (?, ?, ?, 1, datetime('now'), ?)
        ''', (row['id'], photo_uri, filename, row['user_id']))
        migrated += 1

    print(f'  Migrated {migrated} existing photos to item_photos table')

def verify(db):
    """Verify migration was successful"""
    # Check table exists
    cursor = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='item_photos'")
    if not cursor.fetchone():
        return False

    # Check row counts match
    photo_count = db.execute('SELECT COUNT(*) FROM item_photos').fetchone()[0]
    item_photo_count = db.execute(
        "SELECT COUNT(*) FROM items WHERE photo_uri IS NOT NULL AND photo_uri != ''"
    ).fetchone()[0]
    return photo_count >= item_photo_count

def down(db):
    """Reverse the migration"""
    db.execute('DROP TABLE IF EXISTS item_photos')
    print('  Dropped item_photos table')
