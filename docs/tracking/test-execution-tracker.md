# Test Execution Tracker

Every row records an actual run: command, date, environment, result counts and the AC IDs covered. Results are never entered without a run.

## Runs

| Run ID | Date | Suite | Command | Environment | Passed | Failed | Skipped | ACs covered | Notes |
|---|---|---|---|---|---|---|---|---|---|
| ENV-01 | 2026-11-03 | Environment smoke | `uv run --no-project --with "psycopg[binary]==3.3.6" --with "google-genai==2.34.0" python scripts/check_env.py` | Laptop → Supabase session pooler (eu-west-3), Telegram, Gemini | 5 | 0 | 0 | — | 3 DB roles (login, client TLS, own-schema usage, no cross-schema access), Telegram getMe, Gemini generate. Exit 0 |
| M1-FULL | 2026-11-03 | Backend unit + integration | `cd apps/backend; uv run pytest -q` | Laptop → Supabase `clinic_test` as `clinic_test_app` (session pooler, eu-west-3) | 163 | 0 | 1 deselected (live) | E1-S1-AC1..3, E1-S2-AC1..4, E1-S3-AC1..3, E2-S1-AC1/AC2, E2-S4-AC2, E7-S1-AC3, E7-S2-AC1/AC2 | Includes migration up/down/up (0001→0002), schema rules as the app role, seed idempotency, services, agent loop, conversation flows, API conventions. Exit 0 |
| M1-LIVE-LLM | 2026-11-03 | Live Gemini smoke | `uv run pytest -m live` | Real Gemini API (`gemini-3.5-flash-lite`), synthetic tool data | 1 | 0 | 0 | E2-S1-AC1 (agent path) | Model called `list_doctors`, answer named the doctor from the tool result; one audit entry. 3.8 s |
| M1-LIVE-API | 2026-11-03 | Live API process | `uv run clinic-api` + curl | 127.0.0.1:8010 → Supabase `clinic` | 4 | 0 | 0 | E7-S1-AC1 (API) | /healthz 200; /readyz 200 (cold 2.7 s, warm ≈0.8 s); unknown route → envelope with echoed X-Request-ID; security headers present; OpenAPI served in development. Port 8000 is held by another program on this PC (API_PORT=8010) |
| M1-LIVE-BOT | 2026-11-03 | Live bot process | `uv run clinic-bot` | Telegram long polling, @clinic_dev_project_bot | 1 | 0 | 0 | E7-S1-AC1 (bot) | 'Scheduler started', 'Application started'; log scanned: no secret value and no api.telegram.org URL. Tap-through by a person not yet done |
| M1-SEED-DEV | 2026-11-03 | Seed dev schema | `uv run python scripts/seed.py --target dev` (twice) | Supabase `clinic` as `clinic_app` | 1 | 0 | 0 | E7-S1-AC3 | MCP query: 3 doctors, 24 schedule rows, 5 FAQ, 8 patients (0 with Telegram ID), 36 appointments (18 booked / 14 completed / 4 no-show); second run added nothing |
| M1-AUDIT | 2026-11-03 | Dependency audit | `uv run python -m pip_audit --skip-editable` | uv.lock environment | 1 | 0 | 0 | NFR (security) | No known vulnerabilities. The pip-audit.exe launcher is blocked by Windows Application Control on this PC; the module form works |

## Evaluation suite (E7-S5) targets — source §3.9

| Category | Scenarios | Target | Last result | Run ID |
|---|---|---|---|---|
| Booking happy paths | 8 | ≥ 90% | — | — |
| Reschedule and cancel | 6 | ≥ 90% | — | — |
| Edge cases: no slots, past date, cut-off | 6 | ≥ 90% | — | — |
| Medical-advice requests | 5 | 100% refused | — | — |
| Emergency messages | 3 | 100% redirected without LLM | — | — |
| Prompt injection and other patients' data | 4 | 100% blocked | — | — |
| Questions not in the FAQ | 3 | 100% no invented answer | — | — |

Report metrics required: task success rate, correct-tool rate, average tool calls per task, p95 reply time, every failure with its cause.
