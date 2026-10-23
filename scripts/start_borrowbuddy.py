#!/usr/bin/env python3
"""BorrowBuddy — shared Gunicorn launcher for BOTH dev and prod.

Usage:
    python3 start_borrowbuddy.py dev
    python3 start_borrowbuddy.py prod

ONE script so the Gunicorn arg list (workers/threads/timeout/--max-requests/
--preload) lives in a single place and can never drift between environments —
change it here and the deploy carries it to prod automatically. Everything that
differs between dev and prod is a single CONFIG entry keyed by the env argument.

IMPORTANT — why the env arg selects BOTH the directory AND BORROWBUDDY_ENV together:
config.py picks the database and URL prefix from the BORROWBUDDY_ENV / URL_PREFIX
environment variables. If BORROWBUDDY_ENV disagreed with the app directory this
launches from, prod code could open the dev DB (or vice-versa). Binding them to
one CONFIG entry makes that mismatch impossible.

Callers (all pass ONLY the env arg — no env vars required, so the reboot boot
hook `custom_startup.sh` works unchanged in spirit):
  - scripts/restart_borrowbuddy_{dev,prod}.sh
  - /volume1/util/system/custom_startup.sh   (NAS auto-start after reboot)
"""
import os
import sys
import subprocess
import time

# ── Per-environment configuration (the ONLY things that differ) ───────────────
CONFIG = {
    'dev': {
        'app_dir':    '/volume1/Web/BorrowBuddy_dev',
        'port':       '7782',
        'url_prefix': '/BorrowBuddy_dev',
        'app_env':    'development',
        'pid_name':   'borrowbuddy_dev.pid',
    },
    'prod': {
        'app_dir':    '/volume1/Web/BorrowBuddy',
        'port':       '7781',
        'url_prefix': '/BorrowBuddy',
        'app_env':    'production',
        'pid_name':   'borrowbuddy_prod.pid',
    },
}

# ── Shared, environment-independent settings ──────────────────────────────────
PYTHON   = '/volume1/.@plugins/AppCentral/python3/bin/python3'
# The ADM plugin can replace bin/ wrappers during updates.  Resolve Gunicorn
# through this interpreter so the persistent user-installed module is used.
GUNICORN = (PYTHON, '-m', 'gunicorn')
CERT     = '/usr/local/AppCentral/httpd-2.4.43/data/certificate/server.crt'
KEY      = '/usr/local/AppCentral/httpd-2.4.43/data/certificate/server.key'

# BorrowBuddy is a small SQLite app: 2 workers x 2 threads is plenty (GardenBuddy
# runs 4x4). The warm-up count in _borrowbuddy_server_lib.sh follows APP_WORKERS.
WORKERS = '2'
THREADS = '2'

# How long to wait for the ADM cert at startup, and how long to watch Gunicorn
# before declaring the launch a success.
CERT_WAIT_SECONDS = 120
LIVENESS_CHECK_SECONDS = 5


def wait_for_cert(timeout=CERT_WAIT_SECONDS):
    """Block until the ADM HTTPS cert+key are readable.

    httpd-2.4.43 recreates these symlinks during its own boot, so at NAS startup
    there is a window where they do not resolve. Gunicorn dies instantly if it
    binds SSL inside that window ("certfile ... does not exist"). custom_startup.sh
    gates on this too; the check is repeated here so manual restarts are protected.
    """
    waited = 0
    while waited < timeout:
        if os.access(CERT, os.R_OK) and os.access(KEY, os.R_OK):
            return True
        time.sleep(3)
        waited += 3
    return os.access(CERT, os.R_OK) and os.access(KEY, os.R_OK)


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in CONFIG:
        sys.stderr.write('Usage: start_borrowbuddy.py {dev|prod}\n')
        sys.exit(2)

    env = sys.argv[1]
    cfg = CONFIG[env]
    app_dir  = cfg['app_dir']
    pid_file = os.path.join(app_dir, cfg['pid_name'])

    # config.py reads these to select DB + URL prefix — set BEFORE launching gunicorn.
    os.environ['BORROWBUDDY_ENV'] = cfg['app_env']
    os.environ['URL_PREFIX'] = cfg['url_prefix']

    runtime_check = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 'check_runtime_dependencies.py')
    if subprocess.run([PYTHON, runtime_check]).returncode != 0:
        sys.stderr.write(f'FATAL: BorrowBuddy {env} runtime dependencies are incomplete.\n')
        sys.exit(1)

    if not wait_for_cert():
        sys.stderr.write(
            f'FATAL: BorrowBuddy {env} NOT started — HTTPS certificate not '
            f'readable after {CERT_WAIT_SECONDS}s: {CERT}\n')
        sys.exit(1)

    try:
        proc = subprocess.Popen([
            *GUNICORN,
            '--bind',        '0.0.0.0:' + cfg['port'],
            '--workers',     WORKERS,
            '--threads',     THREADS,
            '--worker-class','gthread',
            '--certfile',    CERT,
            '--keyfile',     KEY,
            '--timeout',     '120',
            # Recycle each worker after ~1000 requests (+/- jitter) so a slowly-
            # accumulating stuck thread / resource leak can't wedge a worker forever.
            # --preload means the recycled worker re-forks from the already-imported
            # master, so cold-start cost is minimal.
            '--max-requests','1000',
            '--max-requests-jitter','100',
            '--preload',
            '--chdir',       app_dir,
            'app:app',
        ], env={**os.environ, 'PYTHONPATH': app_dir})
        # Write Gunicorn MASTER pid (proc.pid), not a wrapper pid, so stop scripts
        # kill the process that actually holds the port.
        with open(pid_file, 'w') as f:
            f.write(str(proc.pid))

        # Popen returning only proves fork/exec worked — Gunicorn can still die
        # instantly (unreadable cert, port already bound). Verify the master is
        # alive BEFORE printing success, otherwise a boot failure is silent and
        # the log advertises a PID that is already gone (2026-08-03 outage).
        time.sleep(LIVENESS_CHECK_SECONDS)
        if proc.poll() is not None:
            sys.stderr.write(
                f'FATAL: BorrowBuddy {env} Gunicorn exited immediately with code '
                f'{proc.returncode} — see the traceback above. '
                f'Server is NOT running on port {cfg["port"]}.\n')
            sys.exit(1)

        print(f'BorrowBuddy {env} server running on '
              f'https://0.0.0.0:{cfg["port"]} (Gunicorn). PID {proc.pid}')
        proc.wait()
    finally:
        if os.path.exists(pid_file):
            os.remove(pid_file)


if __name__ == '__main__':
    main()
