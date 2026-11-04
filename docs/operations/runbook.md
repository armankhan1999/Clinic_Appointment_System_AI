# Operations runbook

How to run, check and recover the clinic system on the demo PC. Commands are PowerShell, run from the
repository root unless stated otherwise. Architecture: [`../architecture/README.md`](../architecture/README.md).

## Start and stop

```powershell
pwsh scripts/start.ps1 -WebPort 3100   # API + Telegram bot (with scheduler) + dashboard; waits until all answer
pwsh scripts/start.ps1 -NoBot          # API + dashboard only (no Telegram polling, no reminders)
pwsh scripts/start.ps1 -Rebuild        # force a fresh dashboard build
pwsh scripts/start.ps1 -Dev            # live development: API restarts on code changes, dashboard via `next dev`
pwsh scripts/stop.ps1                  # stops every process start.ps1 started (whole process trees)
```

| Part | Address | Ready when |
|---|---|---|
| Dashboard | `http://localhost:<WebPort>` (3000 by default; this PC uses 3100) | `/login` answers 200 |
| Staff API | `http://127.0.0.1:<API_PORT>` (`.env`; this PC uses 8010) | `/readyz` answers 200 (database reachable) |
| Telegram bot | long polling | `logs\bot.out.log` contains `"scheduler_heartbeat"` (first reminder run, 15 s after start) |

`start.ps1` gives up after 120 s, stops whatever it started and names the part that failed. Logs:
`logs\<part>.out.log` (JSON lines) and `logs\<part>.err.log`; process ids in `logs\stack.pids`.

## First sign-in to the dashboard

Create your own admin account once (the password is typed twice and never shown):

```powershell
Set-Location apps/backend
uv run python scripts/create_admin.py --target dev --username owner --display-name "Clinic Owner"
```

Further staff accounts are created in the dashboard (Admin → Staff accounts). The E2E test accounts
`e2e_admin` / `e2e_desk` exist in the dev schema; their passwords are only in the git-ignored
`apps/web/.env.local`.

## Health checks

```powershell
Invoke-RestMethod http://127.0.0.1:8010/healthz   # {"status":"ok"}: the process is up
Invoke-RestMethod http://127.0.0.1:8010/readyz    # {"status":"ready"}: the database answers
```

## Log events worth watching

| Event | Level | Meaning | Action |
|---|---|---|---|
| `db_tls_unverified` | warning | Database TLS is encrypted but the server certificate is not verified | Install the Supabase CA and set `DB_SSL_ROOT_CERT` (blocker BLK-05) |
| `llm_unavailable` | warning | One Gemini call failed or exceeded `LLM_TIMEOUT_SECONDS`; the patient got the fallback reply | Check the provider; frequent → faster or paid model tier |
| `agent_budget_exhausted` | warning | A whole reply exceeded `AGENT_TURN_BUDGET_SECONDS` | As above, or database latency (R-LAT-01) |
| `grounding_failed` | warning | The model named a time or fee no tool returned; the reply was replaced | Review the prompt version if frequent |
| `emergency_redirected` | warning | An emergency phrase was answered with the emergency number (no model call) | Staff see the alert on the Today screen |
| `reminder_delivery_failed`, `notification_retry` | warning | Telegram delivery failed; retried | After 3 attempts the appointment is flagged "Needs a call" |
| `reminder_job_failed`, `outbox_job_failed` | error | One scheduler run failed; the next run continues | Read the error fields; check the database |
| `conversation_failed`, `telegram_handler_error` | error | Unexpected error while handling a message; the patient got a short apology | Investigate with the `request_id` |
| `readiness_failed` | warning | `/readyz` could not reach the database | Network or Supabase status |

Logs never contain chat text, names, phone numbers or secrets (redaction in `observability.py`).

## Known issues on this PC

| Symptom | Cause | Fix |
|---|---|---|
| `Failed to spawn: pytest … An Application Control policy has blocked this file (os error 4551)` | Windows Application Control blocks some console-script launchers (`pytest.exe`, `pip-audit.exe`) | `uv run python -m pytest …`, `uv run python -m pip_audit` |
| Port 3000 or 8000 already in use | Other programs on this PC | `-WebPort 3100`; `API_PORT=8010` in `.env` (rebuild the dashboard after changing it) |
| `EADDRINUSE` after stopping a background run, or tests failing with 401s | A stopped shell left its `node`/`python` child running (it may also keep truncating `clinic_test`) | Find it: `Get-CimInstance Win32_Process -Filter "Name='node.exe' OR Name='python.exe'"`; stop only that PID |
| Bot replies "Sorry, I can't answer right now…" | Gemini slower than `LLM_TIMEOUT_SECONDS` per call, or the whole reply over `AGENT_TURN_BUDGET_SECONDS` | Provider latency (R-GEM-02); measured 11–37 s per minimal call on 2026-11-04 afternoon |
| Every bot reply is the fallback; logs show `llm_unavailable … status=429` | Gemini free-tier daily quota used up (500 requests per day per model, QUOTA-01); evaluation runs count against the same quota | Wait for the reset (midnight Pacific time; `retryDelay` in the 429), or use a paid tier; run evaluations in their own Google Cloud project (limits are per project, not per key). Check each model's free limit in AI Studio before switching: `gemini-3.5-flash` allows only 20/day |
| Slow dashboard actions (booking ≈ 6 s) | Database in `eu-west-3`, ~128 ms per round trip (R-LAT-01) | Host the API next to the database, or move the project to `ap-south-1` |

## Database

- Schemas: `clinic` (dev, used by the running app) and `clinic_test` (tests, truncated by every test run).
  Never point tests at `clinic`.
- Migrations: `uv run alembic -x schema=clinic upgrade head` (and `schema=clinic_test`); reversible
  (`downgrade -1`).
- Demo data: `uv run python scripts/seed.py --target dev` (idempotent; refuses `ENV=production`).

## Tests and evaluation

```powershell
Set-Location apps/backend
uv run python -m pytest                       # unit + integration; ~26 min against eu-west-3, ~22 s in CI
uv run python -m pytest -m eval tests/integration/test_agent_eval.py   # 38 scenarios, real Gemini, ~20 min
Set-Location ../web
npm run lint; npx tsc --noEmit; npm run test  # dashboard checks
npx playwright test                            # E2E: needs the running stack and E2E_* in .env.local
```

Integration, live and evaluation runs share `clinic_test`: run one at a time. The evaluation report lands in
`apps/backend/reports/` (git-ignored); copy the ones you keep into `docs/testing/`.

## Releases

Work on a short-lived branch, merge into `main` once checks pass, push `main`; GitHub Actions runs the backend
(lint, types, migrations, tests, pip-audit) and dashboard (lint, types, tests, build, npm audit) jobs on every
push and pull request.
