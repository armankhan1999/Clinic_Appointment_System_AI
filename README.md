# Clinic Appointment Booking Agent

A Telegram assistant that lets patients of a single clinic register, find doctors and manage appointments, plus a staff dashboard. Requirements: [`docs/requirements/source/brd-prd-backlog.md`](docs/requirements/source/brd-prd-backlog.md). Progress: [`PROJECT_TRACKER.md`](PROJECT_TRACKER.md).

| Process | Command (from `apps/backend`) | What it does |
|---|---|---|
| Telegram bot | `uv run clinic-bot` | Long-polls Telegram; consent-first registration; Gemini tool-calling agent |
| Staff API | `uv run clinic-api` | FastAPI on `127.0.0.1:%API_PORT%` (default 8000): `/healthz`, `/readyz`, `/api/v1/*` |
| Dashboard | `npm run start` (from `apps/web`, after `npm run build`) | Next.js staff UI; `/api/v1/*` is rewritten to the API |

Design: [`docs/architecture/`](docs/architecture/README.md) · threat model: [`docs/security/threat-model.md`](docs/security/threat-model.md) · decisions: [`docs/tracking/decision-log.md`](docs/tracking/decision-log.md).

## Prerequisites

- Windows, macOS or Linux with Python 3.14 and [uv](https://docs.astral.sh/uv/) 0.10+
- A Supabase project (one project, schemas `clinic` and `clinic_test`; see D-17 and D-20)
- A Telegram bot token from @BotFather and a Google AI Studio (Gemini) API key

## First-time setup (PowerShell)

```powershell
# 1. Configuration: copy the template and fill in every value (never commit .env)
Copy-Item .env.example .env
notepad .env

# 2. Database bootstrap, once per Supabase project: run infrastructure/db/bootstrap.sql as the
#    project owner (Supabase SQL editor or MCP), then set the role passwords from your .env:
python scripts/db_role_passwords.py   # prints ALTER ROLE ... SCRAM verifiers; run them as the owner

# 3. Check every credential without printing secrets
uv run --no-project --with "psycopg[binary]==3.3.6" --with "google-genai==2.34.0" python scripts/check_env.py

# 4. Install the backend, create the schema and load the synthetic demo clinic
Set-Location apps/backend
uv sync
uv run alembic -x schema=clinic upgrade head
uv run alembic -x schema=clinic_test upgrade head
uv run python scripts/seed.py --target dev

# 5. Create the first admin account (the password is typed twice and never shown)
uv run python scripts/create_admin.py --target dev --username owner --display-name "Clinic Owner"
```

## Run

One command starts the API, the Telegram bot with its reminder scheduler, and the dashboard. It builds the
dashboard when needed, waits until every part answers (limit 2 minutes), and writes logs to `logs\`:

```powershell
pwsh scripts/start.ps1               # dashboard on http://localhost:3000
pwsh scripts/start.ps1 -WebPort 3100 # if port 3000 is taken (it is on the original dev PC)
pwsh scripts/start.ps1 -NoBot        # API and dashboard only
pwsh scripts/stop.ps1                # stops everything start.ps1 started
```

Or run each part in its own terminal:

```powershell
Set-Location apps/backend
uv run clinic-api     # terminal 1
uv run clinic-bot     # terminal 2, then message your bot in Telegram and send /start
```

If the model is unreachable, the bot answers with a short "try again" message and the clinic phone number
instead of failing (E7-S6-AC2).

## Tests

```powershell
Set-Location apps/backend
uv run pytest                      # unit + integration (clinic_test schema); live and eval tests are opt-in
uv run pytest -m live              # real Gemini and Telegram smoke tests
uv run pytest -m eval tests/integration/test_agent_eval.py   # 35-scenario agent evaluation -> reports/eval-*.md
```

Integration, live and evaluation runs share the `clinic_test` schema: run them one at a time. If Windows
Application Control blocks the `pytest.exe` launcher (os error 4551), use `uv run python -m pytest …`.

## Dashboard

The staff dashboard is a Next.js app in [`apps/web`](apps/web/README.md) (Node.js 22+: the test tooling's jsdom dependencies declare 22.22+ or 24.15+; Next.js alone needs 20.9+). The browser only talks to the dashboard's origin; `/api/v1/*` is rewritten to the API on `127.0.0.1:%API_PORT%`, so set `API_PORT` to the same value as the API (8010 on the original dev PC) **before** `npm run dev` or `npm run build`.

```powershell
Set-Location apps/web
npm ci
$env:API_PORT = "8010"
npm run dev            # terminal 3: http://localhost:3000
npm run lint; npx tsc --noEmit; npm run test; npm run build
```

Playwright E2E specs (`npm run test:e2e`) need the API, the dashboard and seeded staff accounts; see [`apps/web/README.md`](apps/web/README.md). Design rules: [`docs/design/design-system.md`](docs/design/design-system.md).

## Test and check

```powershell
Set-Location apps/backend
uv run ruff check; uv run ruff format --check; uv run mypy
uv run pytest                       # unit + integration (uses schema clinic_test as clinic_test_app)
uv run pytest -m live               # real Gemini call with synthetic data
uv run python -m pip_audit --skip-editable   # dependency vulnerabilities
```

Integration tests need the `.env` database settings; they never touch the `clinic` schema (the test role has no rights on it). CI (`.github/workflows/ci.yml`) runs the same checks against a throwaway Postgres 17 container.

## Configuration notes

| Setting | Why it matters |
|---|---|
| `DB_HOST` | Must be the Supabase **session pooler** (`aws-N-<region>.pooler.supabase.com`, port 5432). The direct host is IPv6-only (D-15a). |
| `DB_SSL_ROOT_CERT` | Path to the Supabase CA (`prod-ca-2021.crt`, Dashboard → Database Settings → SSL Configuration). Enables certificate verification; **required in production**. Without it, dev/test use encrypted but unverified TLS and log a warning. |
| `API_PORT` | Change it if port 8000 is taken (it is on the original dev PC, so `.env` uses 8010). |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` by default (D-13). The free tier may use prompts for training, so only synthetic data is used and the model never receives patient identity (D-16). |

## Troubleshooting

- `Psycopg cannot use the 'ProactorEventLoop'`: not used at runtime; the backend uses asyncpg (D-25). psycopg is only in `scripts/check_env.py`.
- `pip-audit` blocked by Windows Application Control: run it as a module, `uv run python -m pip_audit`.
- `tenant/user ... not found` from the pooler: wrong pooler host for the project's region (D-23).
