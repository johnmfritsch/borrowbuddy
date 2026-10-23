#!/opt/bin/bash
#
# deploy_to_prod.sh — BorrowBuddy: Deploy Dev to Prod (with automatic migrations)
#
# Same shape as GardenBuddy's deploy: runtime preflight, dev->prod diff,
# migration status, confirm, PID-based stop, full backup, rsync, migrate,
# restart with a /health readiness check, rollback instructions on failure.

PYTHON=/volume1/.@plugins/AppCentral/python3/bin/python3
# Deploys are intentionally run by root so they can stop prod and write the
# deployment backup.  ADM's Python update moved the shared packages to the
# app user's persistent site; expose that site to this root-launched process.
PYTHONUSERBASE=/home/<user>/.local
export PYTHONUSERBASE
PYTHON_USER_SITE=$("$PYTHON" -c 'import site; print(site.getusersitepackages())')
export PYTHONPATH="$PYTHON_USER_SITE${PYTHONPATH:+:$PYTHONPATH}"

DEV_DIR="/volume1/Web/BorrowBuddy_dev"
PROD_DIR="/volume1/Web/BorrowBuddy"
# Mirrors config.py's ProductionConfig.URL_PREFIX / PORT — bash can't share that
# definition, so this is the one place to update it on this side.
EXTERNAL_HOST="fritsch-nas.myasustor.com"
PROD_PORT="7781"
# Prod deploy tarballs live in prod's own backups/. The tar excludes backups/ so it
# never contains itself, and rollback extraction never touches it. Retention
# (keep newest 5) is applied by scripts/cleanup_backups.sh at the end of a deploy.
BACKUP_DIR="$PROD_DIR/backups"

# What is NOT copied from dev to prod. Used by BOTH the dry-run diff and the real
# rsync so the two can never disagree.
RSYNC_EXCLUDES=(
    --exclude='data/'
    --exclude='backups/'
    --exclude='logs/'
    --exclude='static/images/'      # user-uploaded photos (must not overwrite)
    --exclude='TRASH/'
    --exclude='__pycache__/'
    --exclude='*.pyc'
    --exclude='*.pid'
    --exclude='*.backup*'
    --exclude='*.bak'
    --exclude='*.log'
    --exclude='*.ctl'
    --exclude='nohup.out'
    --exclude='secret_key.txt'
    --exclude='deploy_to_prod.sh'   # points at dev; never runs from prod
    --exclude='HANDOFF.md'          # dev working checkpoint
    --exclude='BACKLOG.md'          # dev working notes
    --exclude='scripts/stop_borrowbuddy_dev.sh'
    --exclude='scripts/restart_borrowbuddy_dev.sh'
    # Legacy dev-only launchers, kept in dev until the boot script is switched over:
    --exclude='start_dev.py'
    --exclude='start_dev_debug.py'
    --exclude='restart_borrowbuddy_dev.sh'
    --exclude='setup_dev_environment.sh'
    --exclude='run.sh'
    --exclude='run_on_7781.sh'
)

echo "========================================="
echo "BorrowBuddy Deployment with Migrations"
echo "========================================="
echo ""

# --- Validate prod dir ---
if [ ! -d "$PROD_DIR" ]; then
    echo "PROD directory not found at $PROD_DIR."
    printf "Create it now? (y/N): "
    read -r yn
    case "$yn" in
        [yY]) mkdir -p "$PROD_DIR" && echo "  Created $PROD_DIR." ;;
        *) echo "Cancelled."; exit 0 ;;
    esac
fi

# --- Step 0: Runtime preflight ---
# Run this before stopping, backing up, or copying anything. ADM updates can
# replace its Python package area; a missing dependency must leave the current
# production server untouched.
echo "Step 0: Checking Python runtime..."
if ! "$PYTHON" "$DEV_DIR/scripts/check_runtime_dependencies.py"; then
    echo "  x Python runtime is incomplete. Production was not changed."
    exit 1
fi

# --- Step 1: Code differences ---
echo ""
echo "Step 1: Checking for code differences..."
CODE_DIFF=$(rsync -acv --dry-run "${RSYNC_EXCLUDES[@]}" "$DEV_DIR/" "$PROD_DIR/" 2>&1)
# Count lines that start with a file path (not summary lines)
CODE_DIFF_COUNT=$(echo "$CODE_DIFF" | grep -cvE "^(sending|sent|total|received|\./|$)|/$" || true)
if [ "$CODE_DIFF_COUNT" -gt 0 ]; then
    echo "  Found $CODE_DIFF_COUNT changed/new file(s):"
    echo "$CODE_DIFF" | grep -vE "^(sending|sent|total|received|\./|$)|/$" | sed 's/^/    /'
else
    echo "  No code changes"
fi

# --- Step 2: Schema and migration differences ---
echo ""
echo "Step 2: Checking for schema and migration differences..."
cd "$DEV_DIR"
"$PYTHON" schema_diff.py
SCHEMA_DIFF=$?

# Dev's migration files against prod's database. (--migrations is explicit: the
# runner's default is PROD's migrations dir, which would hide new dev migrations.)
PENDING_OUTPUT=$("$PYTHON" migrate.py status --db "$PROD_DIR/data/borrowbuddy.db" --migrations "$DEV_DIR/migrations" 2>&1)
PENDING_COUNT=$(echo "$PENDING_OUTPUT" | grep -c "Pending" || true)
if [ "$PENDING_COUNT" -gt 0 ]; then
    echo ""
    echo "  Pending migrations that will run on production:"
    echo "$PENDING_OUTPUT" | grep "Pending" | sed 's/^/    /'
else
    echo "  No pending migrations"
fi

# --- Nothing to do? ---
if [ "$CODE_DIFF_COUNT" -eq 0 ] && [ "$PENDING_COUNT" -eq 0 ] && [ "$SCHEMA_DIFF" -eq 0 ]; then
    echo ""
    echo "==========================================="
    echo "  Dev and Prod are in sync - nothing to do"
    echo "==========================================="
    exit 0
fi

echo ""
printf "Do you want to continue with deployment? (yes/no): "
read -r confirm
if [ "$confirm" != "yes" ]; then
    echo "Deployment cancelled."
    exit 0
fi

# --- Step 3: Stop prod server ---
echo ""
echo "Step 3: Stopping production server..."
PROD_STOP="$PROD_DIR/scripts/stop_borrowbuddy_prod.sh"
if [ -f "$PROD_STOP" ]; then
    /opt/bin/bash "$PROD_STOP" || echo "  (PROD server was not running)"
else
    # One-time case: prod still runs the pre-Gunicorn server, which has no PID
    # file and no stop script. Release the port (not a process-name match) so the
    # old server is not running while we back up and migrate.
    echo "  No stop script in prod yet (first deploy of the Gunicorn launcher) — releasing port $PROD_PORT."
    fuser -k "${PROD_PORT}/tcp" 2>/dev/null || echo "  (nothing was listening on $PROD_PORT)"
    sleep 2
fi

# --- Step 4: Backup prod ---
# Uncompressed on purpose: most of prod's static/images is already-compressed JPEG,
# so gzip burns CPU without shrinking it (same reasoning as GardenBuddy, 2026-08-21).
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/borrowbuddy_prod_${TIMESTAMP}.tar"
echo ""
echo "Step 4: Creating backup..."
mkdir -p "$BACKUP_DIR"
cd "$PROD_DIR/.."
tar -cf "$BACKUP_FILE" --exclude='BorrowBuddy/backups' BorrowBuddy/ 2>/dev/null || true
echo "  Backup: $BACKUP_FILE"

# --- Step 5: Rsync dev -> prod ---
echo ""
echo "Step 5: Copying development code to production..."
rsync -a --quiet "${RSYNC_EXCLUDES[@]}" "$DEV_DIR/" "$PROD_DIR/"
echo "  Code copied (data, images, logs and dev-only files excluded)"

# Clean Python cache
find "$PROD_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$PROD_DIR" -type f -name "*.pyc" -delete 2>/dev/null || true
mkdir -p "$PROD_DIR/data" "$PROD_DIR/logs" "$PROD_DIR/backups"

# --- Step 6: Run migrations ---
echo ""
echo "Step 6: Running database migrations..."
cd "$PROD_DIR"
"$PYTHON" migrate.py up --db "$PROD_DIR/data/borrowbuddy.db" --migrations "$PROD_DIR/migrations"

if [ $? -ne 0 ]; then
    echo ""
    echo "  x Migration failed!"
    echo "  Rolling back deployment..."
    cd "$PROD_DIR/.."
    tar -xf "$BACKUP_FILE"
    # The restored code decides which launcher can start it: a pre-Gunicorn
    # backup has no /health route, so the new restart script's readiness poll
    # would fail against it.
    if grep -q "health_bp" "$PROD_DIR/app.py" 2>/dev/null && [ -f "$PROD_DIR/scripts/restart_borrowbuddy_prod.sh" ]; then
        /opt/bin/bash "$PROD_DIR/scripts/restart_borrowbuddy_prod.sh"
    elif [ -f "$PROD_DIR/restart_borrowbuddy.sh" ]; then
        (cd "$PROD_DIR" && ./restart_borrowbuddy.sh)
    else
        echo "  No restart script found for the restored code — start prod manually."
    fi
    echo "  Rollback complete. Check migration errors above."
    exit 1
fi

# --- Step 7: Restart prod server ---
echo ""
echo "Step 7: Restarting production server..."
PROD_RESTART="$PROD_DIR/scripts/restart_borrowbuddy_prod.sh"
if [ -f "$PROD_RESTART" ]; then
    # The restart script runs a readiness poll and exits non-zero if the server
    # does not actually come up and serve /health. Honor that exit code.
    /opt/bin/bash "$PROD_RESTART"
    RESTART_RC=$?
    if [ "$RESTART_RC" -ne 0 ]; then
        echo ""
        echo "==========================================="
        echo "  x DEPLOY FAILED — prod did not come back up"
        echo "==========================================="
        echo "  The restart readiness check failed (exit $RESTART_RC)."
        echo "  Recent prod log:"
        tail -n 20 "$PROD_DIR/logs/borrowbuddy_prod.log" 2>/dev/null | sed 's/^/    /'
        echo ""
        echo "  Code is deployed but the server is NOT confirmed healthy."
        echo "  To roll back to the pre-deploy backup:"
        echo "    1. /opt/bin/bash $PROD_DIR/scripts/stop_borrowbuddy_prod.sh"
        echo "    2. tar -xf $BACKUP_FILE -C /volume1/Web"
        echo "    3. cd $PROD_DIR && ./restart_borrowbuddy.sh    (pre-Gunicorn code)"
        exit 1
    fi
    echo "  Server restarted and confirmed healthy (PID $(cat "$PROD_DIR/borrowbuddy_prod.pid" 2>/dev/null))"
else
    echo "  x restart_borrowbuddy_prod.sh not found in prod — nothing was restarted."
    exit 1
fi

echo ""
echo "========================================="
echo "  Deployment Complete!"
echo "========================================="
echo ""
echo "  Production: https://$EXTERNAL_HOST:$PROD_PORT/BorrowBuddy/"
echo "  Backup:     $BACKUP_FILE"
echo ""
echo "  To rollback:"
echo "    1. /opt/bin/bash $PROD_DIR/scripts/stop_borrowbuddy_prod.sh"
echo "    2. tar -xf $BACKUP_FILE -C /volume1/Web"
echo "    3. restart with the restart script that matches the restored code"
echo ""

# Final schema check
cd "$DEV_DIR"
"$PYTHON" schema_diff.py > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo "  Dev and Prod schemas are now in sync"
else
    echo "  WARNING: Schema differences remain — run: $PYTHON $DEV_DIR/schema_diff.py"
fi
echo ""

# --- Backup retention (non-fatal) ---
/opt/bin/bash "$DEV_DIR/scripts/cleanup_backups.sh" || true
echo ""
