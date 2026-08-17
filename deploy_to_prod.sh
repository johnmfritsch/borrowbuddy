#\!/opt/bin/bash
# Enhanced Deploy with Automatic Migrations

echo "========================================="
echo "BorrowBuddy Deployment with Migrations"
echo "========================================="
echo ""

PROD_DIR="/volume1/Web/BorrowBuddy"
DEV_DIR="/volume1/Web/BorrowBuddy_dev"
BACKUP_DIR="/volume1/Web/BorrowBuddy_backups"

# Step 1: Check for code differences (rsync dry-run)
echo "Step 1: Checking for code differences..."
CODE_DIFF=$(rsync -acv --dry-run     --exclude="data/"     --exclude="static/images/"     --exclude="__pycache__/"     --exclude="*.pyc"     --exclude="TRASH/"     --exclude="*.backup*"     --exclude="*.bak"     --exclude="*.log"     --exclude="start_dev.py"     --exclude="start_dev_debug.py"     --exclude="restart_borrowbuddy_dev.sh"     --exclude="setup_dev_environment.sh"     --exclude="run.sh"     --exclude="run_on_7781.sh"     --exclude="secret_key.txt"     "$DEV_DIR/" "$PROD_DIR/" 2>&1)
# Count lines that start with a file path (not summary lines)
CODE_DIFF_COUNT=$(echo "$CODE_DIFF" | grep -cvE "^(sending|sent|total|received|\./|$)|/$" || true)
if [ $CODE_DIFF_COUNT -gt 0 ]; then
    echo "  Found $CODE_DIFF_COUNT changed/new file(s):"
    echo "$CODE_DIFF" | grep -vE "^(sending|sent|total|received|\./|$)|/$" | sed 's/^/    /'
else
    echo "  ✓ No code changes"
fi

# Step 2: Check for schema/migration differences
echo ""
echo "Step 2: Checking for schema and migration differences..."
cd "$DEV_DIR"
python3 schema_diff.py
SCHEMA_DIFF=$?

# Check what migrations would run on prod (use dev migration files against prod db)
cd "$DEV_DIR"
PENDING_OUTPUT=$(python3 migrate.py status --db "$PROD_DIR/data/borrowbuddy.db" 2>&1)
PENDING_COUNT=$(echo "$PENDING_OUTPUT" | grep "⧗ Pending" | wc -l)

if [ $PENDING_COUNT -gt 0 ]; then
    echo ""
    echo "Pending migrations that will run on production:"
    echo "$PENDING_OUTPUT" | grep "⧗ Pending" | sed 's/^/  /'
else
    echo "  ✓ No pending migrations"
fi

# Exit only if there is truly nothing to do
if [ $CODE_DIFF_COUNT -eq 0 ] && [ $PENDING_COUNT -eq 0 ] && [ $SCHEMA_DIFF -eq 0 ]; then
    echo ""
    echo "==========================================="
    echo "✓ Dev and Prod are in sync - No deployment needed"
    echo "==========================================="
    exit 0
fi

echo ""
read -p "Do you want to continue with deployment? (yes/no): " confirm
if [ "$confirm" \!= "yes" ]; then
    echo "Deployment cancelled."
    exit 0
fi

# Step 3: Stop production server
echo ""
echo "Step 3: Stopping production server..."
pkill -f "port=7781"
sleep 3

# Step 4: Backup EVERYTHING in production (no exclusions)
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/borrowbuddy_prod_$TIMESTAMP.tar.gz"
echo ""
echo "Step 4: Creating backup..."
mkdir -p "$BACKUP_DIR"
cd "$PROD_DIR/.."
tar -czf "$BACKUP_FILE" BorrowBuddy/ 2>/dev/null
echo "  ✓ Backup: $BACKUP_FILE"

# Step 5: Copy code from dev to prod
# Excludes:
#   data/              - production database (must not overwrite)
#   static/images/     - user-uploaded photos (must not overwrite)
#   TRASH/             - dev cleanup archive
#   *.backup* / *.bak  - dev backup files
#   *.log              - dev log files
#   __pycache__/       - Python bytecode cache
#   *.pyc              - compiled Python files
#   Dev-only scripts   - start_dev.py, restart_borrowbuddy_dev.sh, etc.
echo ""
echo "Step 5: Copying development code to production..."
rsync -a --quiet     --exclude="data/"     --exclude="static/images/"     --exclude="__pycache__/"     --exclude="*.pyc"     --exclude="TRASH/"     --exclude="*.backup*"     --exclude="*.bak"     --exclude="*.log"     --exclude="start_dev.py"     --exclude="start_dev_debug.py"     --exclude="restart_borrowbuddy_dev.sh"     --exclude="setup_dev_environment.sh"     --exclude="run.sh"     --exclude="run_on_7781.sh"     --exclude="secret_key.txt"     "$DEV_DIR/" "$PROD_DIR/"
echo "  ✓ Code copied (data, images, dev-only files excluded)"

# Clean up any Python cache that might have been copied
echo "  Cleaning Python cache..."
find "$PROD_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
find "$PROD_DIR" -type f -name "*.pyc" -delete 2>/dev/null

# Step 6: Run migrations (AUTOMATIC)
echo ""
echo "Step 6: Running database migrations..."
cd "$PROD_DIR"
python3 migrate.py up

if [ $? -ne 0 ]; then
    echo ""
    echo "✗ Migration failed\!"
    echo "Rolling back deployment..."
    cd "$PROD_DIR/.."
    tar -xzf "$BACKUP_FILE"
    cd "$PROD_DIR"
    ./restart_borrowbuddy.sh
    echo "Rollback complete. Check migration errors above."
    exit 1
fi

# Step 7: Restart production (with error checking)
echo ""
echo "Step 7: Restarting production server..."
cd "$PROD_DIR"
./restart_borrowbuddy.sh

# Wait a moment and verify server started
sleep 5
if ps aux | grep 'port=7781' | grep python | grep -v grep > /dev/null; then
    echo "  ✓ Server restarted successfully"
else
    echo "  ✗ Warning: Server may not have started correctly"
    echo "  Check log: tail /tmp/borrowbuddy_7781.log"
    echo "  Manual restart: cd $PROD_DIR && ./restart_borrowbuddy.sh"
fi

echo ""
echo "========================================="
echo "✓ Deployment Complete\!"
echo "========================================="
echo ""
echo "Production: https://192.168.x.x:7781/BorrowBuddy/"
echo ""

# Final verification
cd "$DEV_DIR"
python3 schema_diff.py > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo "✓ Dev and Prod schemas are now in sync"
else
    echo "⚠ Note: Some schema differences may remain"
    echo "  Run 'python3 schema_diff.py' to see details"
fi

echo ""
