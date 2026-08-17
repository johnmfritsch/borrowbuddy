"""
Migration 009: Add image variant columns for performance optimization
Created: 2026-02-11
"""

VERSION = '009'
DESCRIPTION = 'Add photo_uri_thumb and photo_uri_display columns for optimized image loading'

def up(db):
    """Apply the migration"""
    # Add columns to item_photos table
    print('  Adding image variant columns to item_photos table...')
    try:
        db.execute('ALTER TABLE item_photos ADD COLUMN photo_uri_thumb TEXT')
        print('    - Added photo_uri_thumb column')
    except Exception as e:
        if 'already exists' in str(e):
            print('    - photo_uri_thumb column already exists')
        else:
            raise

    try:
        db.execute('ALTER TABLE item_photos ADD COLUMN photo_uri_display TEXT')
        print('    - Added photo_uri_display column')
    except Exception as e:
        if 'already exists' in str(e):
            print('    - photo_uri_display column already exists')
        else:
            raise

    # Add columns to items table (denormalized cache)
    print('  Adding image variant columns to items table...')
    try:
        db.execute('ALTER TABLE items ADD COLUMN photo_uri_thumb TEXT')
        print('    - Added photo_uri_thumb column')
    except Exception as e:
        if 'already exists' in str(e):
            print('    - photo_uri_thumb column already exists')
        else:
            raise

    try:
        db.execute('ALTER TABLE items ADD COLUMN photo_uri_display TEXT')
        print('    - Added photo_uri_display column')
    except Exception as e:
        if 'already exists' in str(e):
            print('    - photo_uri_display column already exists')
        else:
            raise

    print('  Image variant columns created successfully')

def verify(db):
    """Verify migration was successful"""
    # Check columns exist in item_photos
    cursor = db.execute("PRAGMA table_info(item_photos)")
    columns = [row[1] for row in cursor.fetchall()]

    if 'photo_uri_thumb' not in columns:
        print('  ERROR: photo_uri_thumb column not found in item_photos')
        return False

    if 'photo_uri_display' not in columns:
        print('  ERROR: photo_uri_display column not found in item_photos')
        return False

    # Check columns exist in items
    cursor = db.execute("PRAGMA table_info(items)")
    columns = [row[1] for row in cursor.fetchall()]

    if 'photo_uri_thumb' not in columns:
        print('  ERROR: photo_uri_thumb column not found in items')
        return False

    if 'photo_uri_display' not in columns:
        print('  ERROR: photo_uri_display column not found in items')
        return False

    print('  All image variant columns verified')
    return True

def down(db):
    """Reverse the migration"""
    print('  Removing image variant columns...')
    try:
        db.execute('ALTER TABLE item_photos DROP COLUMN photo_uri_thumb')
        db.execute('ALTER TABLE item_photos DROP COLUMN photo_uri_display')
        db.execute('ALTER TABLE items DROP COLUMN photo_uri_thumb')
        db.execute('ALTER TABLE items DROP COLUMN photo_uri_display')
        print('  Image variant columns removed')
    except Exception as e:
        print(f'  WARNING: Error removing columns: {e}')
