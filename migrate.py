#!/usr/bin/env python3
"""
BorrowBuddy Migration Runner
Automatically discovers and runs database migrations in order
"""
import sqlite3
import sys
import importlib.util
from datetime import datetime
from pathlib import Path

class MigrationRunner:
    def __init__(self, db_path, migrations_dir):
        self.db_path = db_path
        self.migrations_dir = Path(migrations_dir)
        self.db = None

    def connect(self):
        """Connect to database and ensure migrations table exists"""
        self.db = sqlite3.connect(self.db_path)
        self.db.row_factory = sqlite3.Row
        self._ensure_migrations_table()

    def _ensure_migrations_table(self):
        """Create schema_migrations table if it doesn't exist"""
        self.db.execute('''
            CREATE TABLE IF NOT EXISTS schema_migrations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                version TEXT UNIQUE NOT NULL,
                description TEXT,
                applied_at TEXT NOT NULL,
                checksum TEXT,
                execution_time_ms INTEGER
            )
        ''')
        self.db.execute('CREATE INDEX IF NOT EXISTS idx_migrations_version ON schema_migrations(version)')
        self.db.commit()

    def discover_migrations(self):
        """Find all migration files and load them"""
        migrations = []

        if not self.migrations_dir.exists():
            return migrations

        for file in sorted(self.migrations_dir.glob('[0-9][0-9][0-9]_*.py')):
            try:
                # Load migration module dynamically
                spec = importlib.util.spec_from_file_location(file.stem, file)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                migrations.append({
                    'file': file,
                    'version': module.VERSION,
                    'description': module.DESCRIPTION,
                    'up': module.up,
                    'down': getattr(module, 'down', None),
                    'verify': getattr(module, 'verify', None)
                })
            except Exception as e:
                print(f"  ✗ Error loading {file.name}: {e}")

        return migrations

    def get_applied_migrations(self):
        """Get list of migrations that have been applied"""
        cursor = self.db.execute('SELECT version FROM schema_migrations ORDER BY version')
        return [row['version'] for row in cursor.fetchall()]

    def get_pending_migrations(self):
        """Get migrations that haven't been applied yet"""
        all_migrations = self.discover_migrations()
        applied = set(self.get_applied_migrations())
        return [m for m in all_migrations if m['version'] not in applied]

    def run_migration(self, migration, dry_run=False):
        """Execute a single migration"""
        version = migration['version']
        description = migration['description']

        print(f"\n{'[DRY RUN] ' if dry_run else ''}Running migration {version}: {description}")

        if dry_run:
            print("  (Migration would run here)")
            return True

        start_time = datetime.now()

        try:
            # Run the migration
            migration['up'](self.db)

            # Verify if verification function exists
            if migration['verify']:
                if not migration['verify'](self.db):
                    raise Exception("Migration verification failed")

            # Record migration
            end_time = datetime.now()
            execution_time = int((end_time - start_time).total_seconds() * 1000)

            self.db.execute('''
                INSERT INTO schema_migrations (version, description, applied_at, execution_time_ms)
                VALUES (?, ?, ?, ?)
            ''', (version, description, datetime.now().isoformat(), execution_time))

            self.db.commit()
            print(f"  ✓ Completed in {execution_time}ms")
            return True

        except Exception as e:
            print(f"  ✗ Failed: {e}")
            self.db.rollback()
            return False

    def run_all_pending(self, dry_run=False):
        """Run all pending migrations"""
        pending = self.get_pending_migrations()

        if not pending:
            print("✓ No pending migrations")
            return True

        print(f"\n{'[DRY RUN] ' if dry_run else ''}Found {len(pending)} pending migration(s)")

        for migration in pending:
            if not self.run_migration(migration, dry_run):
                print("\n✗ Migration failed, stopping")
                return False

        print(f"\n✓ All migrations {'would be' if dry_run else 'were'} applied successfully")
        return True

    def status(self):
        """Show migration status"""
        all_migrations = self.discover_migrations()
        applied = set(self.get_applied_migrations())

        print("\n=== Migration Status ===\n")

        if not all_migrations:
            print("No migrations found")
            return

        for migration in all_migrations:
            version = migration['version']
            description = migration['description']
            status = '✓ Applied' if version in applied else '⧗ Pending'
            print(f"{status}  {version}: {description}")

        pending_count = len([m for m in all_migrations if m['version'] not in applied])
        print(f"\n{len(applied)} applied, {pending_count} pending")

    def close(self):
        """Close database connection"""
        if self.db:
            self.db.close()

def main():
    import argparse

    parser = argparse.ArgumentParser(description='BorrowBuddy Migration Runner')
    parser.add_argument('command', choices=['status', 'up'], help='Command to execute')
    parser.add_argument('--dry-run', action='store_true', help='Show what would happen without executing')
    parser.add_argument('--db', default='/volume1/Web/BorrowBuddy/data/borrowbuddy.db', help='Database path')
    parser.add_argument('--migrations', default='/volume1/Web/BorrowBuddy/migrations', help='Migrations directory')

    args = parser.parse_args()

    runner = MigrationRunner(args.db, args.migrations)

    try:
        runner.connect()

        if args.command == 'status':
            runner.status()
            return 0
        elif args.command == 'up':
            success = runner.run_all_pending(args.dry_run)
            return 0 if success else 1

    except Exception as e:
        print(f"\n✗ Error: {e}")
        return 1
    finally:
        runner.close()

if __name__ == '__main__':
    sys.exit(main())
