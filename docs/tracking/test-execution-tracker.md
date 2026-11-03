# Test Execution Tracker

Every row records an actual run: command, date, environment, result counts and the AC IDs covered. Results are never entered without a run.

## Runs

| Run ID | Date | Suite | Command | Environment | Passed | Failed | Skipped | ACs covered | Notes |
|---|---|---|---|---|---|---|---|---|---|
| ENV-01 | 2026-11-03 | Environment smoke | `uv run --no-project --with "psycopg[binary]==3.3.6" --with "google-genai==2.34.0" python scripts/check_env.py` | Laptop → Supabase session pooler (eu-west-3), Telegram, Gemini | 5 | 0 | 0 | — | 3 DB roles (login, client TLS, own-schema usage, no cross-schema access), Telegram getMe, Gemini generate. Exit 0 |

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
