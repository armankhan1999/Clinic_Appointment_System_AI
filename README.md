# Clinic Appointment Booking Agent

A Telegram assistant that lets patients of a single clinic register, find doctors and manage appointments, plus a staff dashboard. Requirements: [`docs/requirements/source/brd-prd-backlog.md`](docs/requirements/source/brd-prd-backlog.md). Progress: [`PROJECT_TRACKER.md`](PROJECT_TRACKER.md).

| Process | Command (from `apps/backend`) | What it does |
|---|---|---|
| Telegram bot | `uv run clinic-bot` | Long-polls Telegram; consent-first registration; Gemini tool-calling agent; reminder job (every 5 min) and clinic-notice outbox job (every minute) |
| Staff API | `uv run clinic-api` | FastAPI on `127.0.0.1:%API_PORT%` (default 8000): `/healthz`, `/readyz`, `/api/v1/*` |
| Dashboard | `npm run start` (from `apps/web`, after `npm run build`) | Next.js staff UI; `/api/v1/*` is rewritten to the API |

Design: [`docs/architecture/`](docs/architecture/README.md) · API contract: [`docs/api/staff-api.md`](docs/api/staff-api.md) · threat model: [`docs/security/threat-model.md`](docs/security/threat-model.md) · security review: [`docs/security/security-review.md`](docs/security/security-review.md) · decisions: [`docs/tracking/decision-log.md`](docs/tracking/decision-log.md) · operations: [`docs/operations/runbook.md`](docs/operations/runbook.md) · acceptance: [`docs/testing/acceptance-report.md`](docs/testing/acceptance-report.md).

## Status

All 32 stories of the source have an implementation: the Telegram bot and agent, the staff API and dashboard, reminders and clinic-side notices, and the 38-scenario evaluation suite. The [story tracker](docs/tracking/user-story-tracker.md) lists 31 as COMPLETED and E2-S1 as TESTING (E2-S1-AC3 still lacks a genuine evaluation pass). Where the build differs from the source on purpose (Next.js instead of Streamlit, Postgres only, a PowerShell start script instead of Docker Compose), see [`docs/architecture/README.md`](docs/architecture/README.md#built-versus-source).

Not met or not done yet (details in the [acceptance report](docs/testing/acceptance-report.md)):

- **Reply time (NFR-01, ≤ 5 s for 95% of messages) is not met** on the dev PC: in the recorded runs the free-tier model alone took a median of 5.5–8.0 s per turn.
- **The evaluation targets of §3.9 are met only with a 45 s diagnostic budget** (35/35, AEV-DIAG-03); at the production settings the last complete run passed 19/35 (AEV-PROD-02), every failure being a model call over 8 s. The final run of all 38 scenarios at production settings has not produced results: it was stopped twice by the Gemini free-tier quota (500 requests per day, shared with the bot).
- Verified database TLS needs the Supabase CA certificate, which is not yet installed on the dev PC (BLK-05); a person has not yet tapped through registration, booking and reminders in Telegram (BLK-06).
- No cloud deployment, backup/restore procedure or privacy assessment exists.

## Prerequisites

- Python 3.14 and [uv](https://docs.astral.sh/uv/) 0.10+; Node.js 22+ for the dashboard (see [Dashboard](#dashboard)).
- Windows with PowerShell 7 (`pwsh`) for the one-command scripts: they use `Get-NetTCPConnection` and `taskkill`. The backend and dashboard also install, test and build on Linux in CI (`ubuntu-latest`); macOS is not verified.
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
pwsh scripts/start.ps1 -WebPort 3100 -Dev  # live development: dashboard updates instantly (next dev)
pwsh scripts/restart.ps1 -Part api   # after backend changes: restart only the API (or -Part bot)
pwsh scripts/stop.ps1                # stops everything start.ps1 started
```

Then open the dashboard and sign in with the admin account from setup step 5, and message the bot in
Telegram (send `/start`). Health: `http://127.0.0.1:%API_PORT%/healthz` and `/readyz`. Log events and
known issues: [`docs/operations/runbook.md`](docs/operations/runbook.md).

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
uv run pytest -m eval tests/integration/test_agent_eval.py   # 38-scenario agent evaluation -> reports/eval-*.md
```

The evaluation suite calls the real model and uses the same free-tier daily quota as the bot; `EVAL_RUNS=N` repeats every scenario. Neither the live tests nor the evaluation suite run in CI. Integration, live and evaluation runs share the `clinic_test` schema: run them one at a time. If Windows
Application Control blocks the `pytest.exe` launcher (os error 4551), use `uv run python -m pytest …`.

## Dashboard

The staff dashboard is a Next.js app in [`apps/web`](apps/web/README.md) (Node.js 22 or newer, as `package.json` `engines` says; the test tooling's jsdom 30.1.3 declares Node `^22.22.2 || ^24.15.0 || >=26.0.0`, and Next.js alone needs 20.9+; CI uses Node 24). The browser only talks to the dashboard's origin; `/api/v1/*` is rewritten to the API on `127.0.0.1:%API_PORT%`, so set `API_PORT` to the same value as the API (8010 on the original dev PC) **before** `npm run dev` or `npm run build`.

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

Integration tests need the `.env` database settings; they never touch the `clinic` schema (the test role has no rights on it). CI (`.github/workflows/ci.yml`) runs ruff, the format check, mypy, the default `pytest` run and `pip-audit` against a throwaway Postgres 17 container, and the dashboard's lint, type check, unit tests, build and `npm audit`. It does not run the live tests, the evaluation suite or the Playwright E2E specs.

## Configuration notes

| Setting | Why it matters |
|---|---|
| `DB_HOST` | Must be the Supabase **session pooler** (`aws-N-<region>.pooler.supabase.com`, port 5432). The direct host is IPv6-only (D-15a). |
| `DB_SSL_ROOT_CERT` | Path to the Supabase CA (`prod-ca-2021.crt`, Dashboard → Database Settings → SSL Configuration). Enables certificate verification; **required in production**. Without it, dev/test use encrypted but unverified TLS and log a warning. |
| `API_PORT` | Change it if port 8000 is taken (it is on the original dev PC, so `.env` uses 8010). |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` by default (D-13, D-38). Free-tier daily limits are per project and per model (500 requests/day for this model, 20 for `gemini-3.5-flash`) and reset at midnight Pacific time. The free tier may use prompts for training, so only synthetic data is used and the model never receives patient identity (D-16). |
| `LLM_TIMEOUT_SECONDS`, `AGENT_TURN_BUDGET_SECONDS` | Default 8 and 25 (D-34). One model call past 8 s counts as the model being unreachable and the patient gets the fallback reply with the clinic phone number; a whole turn may take up to 25 s while the model keeps answering. The turn budget may not be smaller than the call timeout. |
| `AUTH_SECRET` | At least 32 random characters. Keys the hashes of attempted unknown staff usernames (lockout without storing the names). |
| `CLINIC_TIMEZONE` | IANA time zone written into the clinic settings by the seed script (`Asia/Kolkata` in `.env.example`); afterwards an admin changes it in the dashboard. The other clinic details (name, phone, address, emergency number and phrases, limits) come from the seed script and the dashboard, not from `.env`. |

## Troubleshooting

- `Psycopg cannot use the 'ProactorEventLoop'`: not used at runtime; the backend uses asyncpg (D-25). psycopg is only in `scripts/check_env.py`.
- `pip-audit` blocked by Windows Application Control: run it as a module, `uv run python -m pip_audit`.
- `tenant/user ... not found` from the pooler: wrong pooler host for the project's region (D-23).
