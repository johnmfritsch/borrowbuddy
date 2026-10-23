# BorrowBuddy 📚

A self-hosted web application for tracking borrowed and loaned items — books, tools, gear, anything. Built for real household use with a clean, mobile-friendly UI.

## Features

- Track items loaned out and borrowed, with quantities
- Per-person contact and loan history
- Photo capture for items and returns, with automatic thumbnail/display variants
- Client-side duplicate-loan detection to catch re-entry mistakes before they hit the database
- Multi-user with authentication and an admin panel
- Audit logging for all changes
- Mobile-friendly responsive UI
- Self-hosted — the data stays on hardware I own

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python / Flask |
| Database | SQLite |
| Frontend | Jinja2 templates + vanilla JavaScript |
| Auth | Session-based authentication |
| Hosting | Self-hosted on ASUSTOR NAS |
| SSL | Let's Encrypt (auto-renewed) |

## Architecture

Flask serves both the HTML UI and a JSON API, running with SSL directly on a dedicated port rather than behind the shared reverse proxy — the router blocks inbound 443, so each externally-reachable app terminates its own TLS on a forwarded port.

Schema changes go through numbered migrations in `migrations/`, applied by `migrate.py`. `schema_diff.py` compares the live schema against what the migrations expect, which catches drift between the dev and production databases.

## Environments

- **Production** — stable release
- **Dev** — active development instance, promoted with `deploy_to_prod.sh`

`deploy_to_prod.sh` checks the Python runtime, diffs dev against prod, shows pending migrations, takes a timestamped backup of production, syncs only code (never the database, uploads, or the secret key), applies migrations, and restarts the service. It treats a server that does not report healthy as a failed deploy.

## Project Structure

```
app.py              # Flask application — routes, auth, API
health.py           # /health liveness probe (no auth, no database)
config.py           # Configuration
utils.py            # Image processing and shared helpers
migrate.py          # Migration runner
schema_diff.py      # Live-schema vs migrations drift check
migrations/         # Numbered schema migrations
templates/          # Jinja2 templates
static/css|js       # Styles and client-side duplicate detection
scripts/            # Gunicorn launcher, stop/restart scripts, runtime check
deploy_to_prod.sh   # Dev → prod promotion with backup
```

## Running from Source

```bash
pip install -r requirements.txt
python app.py        # quick local run
```

On the NAS both environments run under Gunicorn through one launcher, `scripts/start_borrowbuddy.py {dev|prod}`. It waits for the HTTPS certificate and writes the Gunicorn master PID to a file; the stop and restart scripts use that PID and wait for `/health` to answer before reporting success.

The Flask secret key is generated into `secret_key.txt` on first run and is not committed. The SQLite database and uploaded photos are runtime data and are likewise excluded — see `.gitignore`.

LAN addresses in this repo are masked as `192.168.x.x`.

_Source snapshot: BorrowBuddy (2026-10-21)._
