#!/usr/bin/env python3
"""
Schema Comparison Tool
Compares dev and prod database schemas to identify differences
"""
import sqlite3
import sys

def get_schema(db_path):
    """Extract complete schema from database"""
    try:
        db = sqlite3.connect(db_path)
        cursor = db.cursor()

        schema = {}

        # Get all tables (exclude SQLite internal tables and migration tracking)
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table'
            AND name NOT LIKE 'sqlite_%'
            AND name != 'schema_migrations'
            ORDER BY name
        """)
        tables = [row[0] for row in cursor.fetchall()]

        for table in tables:
            cursor.execute(f'PRAGMA table_info({table})')
            columns = {row[1]: row[2] for row in cursor.fetchall()}
            schema[table] = columns

        db.close()
        return schema
    except Exception as e:
        print(f"Error reading {db_path}: {e}")
        return None

def compare_schemas(dev_schema, prod_schema):
    """Find differences between schemas"""
    differences = []

    # Check each table in dev
    for table, dev_cols in dev_schema.items():
        if table not in prod_schema:
            differences.append(('table', 'added', table, None, None))
            continue

        prod_cols = prod_schema[table]

        # Check columns
        for col, col_type in dev_cols.items():
            if col not in prod_cols:
                differences.append(('column', 'added', table, col, col_type))
            elif prod_cols[col] != col_type:
                differences.append(('column', 'modified', table, col, f'{prod_cols[col]} -> {col_type}'))

        # Check for removed columns
        for col in prod_cols:
            if col not in dev_cols:
                differences.append(('column', 'removed', table, col, None))

    # Check for removed tables
    for table in prod_schema:
        if table not in dev_schema:
            differences.append(('table', 'removed', table, None, None))

    return differences

def main():
    DEV_DB = '/volume1/Web/BorrowBuddy_dev/data/borrowbuddy_dev.db'
    PROD_DB = '/volume1/Web/BorrowBuddy/data/borrowbuddy.db'

    print("=== Schema Comparison: Dev vs Prod ===\n")

    dev_schema = get_schema(DEV_DB)
    prod_schema = get_schema(PROD_DB)

    if dev_schema is None or prod_schema is None:
        return 1

    differences = compare_schemas(dev_schema, prod_schema)

    if not differences:
        print("✓ Schemas are identical")
        return 0

    print(f"Found {len(differences)} difference(s):\n")

    for diff in differences:
        if diff[0] == 'table':
            action = diff[1]
            table = diff[2]
            symbol = '+' if action == 'added' else '-'
            print(f"  {symbol} Table: {table}")
        elif diff[0] == 'column':
            action = diff[1]
            table = diff[2]
            column = diff[3]
            if diff[4]:
                col_type = diff[4]
                symbol = '+' if action == 'added' else '~' if action == 'modified' else '-'
                print(f"  {symbol} {table}.{column} ({col_type})")
            else:
                print(f"  - {table}.{column}")

    print(f"\n⚠ Production schema is behind development")
    print("  Create migrations for these changes before deploying")

    return 1

if __name__ == '__main__':
    sys.exit(main())
