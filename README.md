# Clinic Appointment Booking Agent

A Telegram assistant that lets patients of a single clinic register, find doctors and manage appointments, plus a staff dashboard. Requirements: [`docs/requirements/source/brd-prd-backlog.md`](docs/requirements/source/brd-prd-backlog.md). Progress: [`PROJECT_TRACKER.md`](PROJECT_TRACKER.md).

| Process | Command (from `apps/backend`) | What it does |
|---|---|---|
| Telegram bot | `uv run clinic-bot` | Long-polls Telegram; consent-first registration; Gemini tool-calling agent |
| Staff API | `uv run clinic-api` | FastAPI on `127.0.0.1:%API_PORT%` (default 8000): `/healthz`, `/readyz`, `/api/v1/*` |
| Dashboard | *(Milestone 5)* | Next.js staff UI |

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
```

## Run

```powershell
Set-Location apps/backend
uv run clinic-api     # terminal 1
uv run clinic-bot     # terminal 2, then message your bot in Telegram and send /start
```

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
