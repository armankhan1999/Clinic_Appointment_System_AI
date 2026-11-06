# Release Readiness

Status as of 2026-11-06. Decision: **NOT READY for go-live.** The application is complete and verified on the dev stack (all 32 stories COMPLETED, every flow used live); go-live waits on the owner actions listed under [Blocks go-live](#blocks-go-live). Detail and evidence: [`../testing/acceptance-report.md`](../testing/acceptance-report.md); run IDs refer to [`test-execution-tracker.md`](test-execution-tracker.md).

States are distinct: Implemented ≠ Tested ≠ Verified ≠ Deployed ≠ Production-ready.

## Gates

| Gate | Criterion | Status | Evidence |
|---|---|---|---|
| Requirements | All 20 Must stories COMPLETED with AC evidence | PASS | `user-story-tracker.md` (all 32 stories COMPLETED), `requirement-traceability-matrix.md`; E2-S1-AC3 closed by XA-01 in AEV-PROD-06 |
| Requirements | Should/Could stories COMPLETED or DEFERRED_WITH_APPROVAL | PASS | All 12 Should/Could stories COMPLETED (`user-story-tracker.md`) |
| Quality | Evaluation suite meets every §3.9 target, or the gap is explained | PASS (gap explained) | AEV-PROD-06 (38 scenarios, production settings): 31/38; edge cases, medical advice, emergencies, injection and not-in-FAQ met; booking 4/8 and reschedule/cancel 5/6 below 90%, all 7 failures one model call over the 8 s per-call timeout (acceptance report). All targets met with the diagnostic budget (AEV-DIAG-03 35/35). Variance not measured: every run used `EVAL_RUNS=1` |
| Quality | Reply time: 95% of replies in 5 s or less (NFR-01) | FAIL | p95 20.3 s in AEV-PROD-06; Gemini free tier about 6–7 s per call (R-GEM-02). See DEC-RT |
| Quality | Concurrency test: 10 parallel bookings → exactly 1 row | PASS | `test_ten_parallel_bookings_for_one_slot_create_exactly_one` (M6-FULL-03); latest full regression M6-FULL-05 424/0 |
| Quality | Reminder restart and Telegram retry tests pass | PASS | `test_reminders_are_never_sent_twice_even_after_a_restart`, `test_delivery_is_retried_three_times_then_flagged_for_staff` (M6-FULL-03); reminders seen live (LIVE-TG-01) |
| Quality | Regression, E2E and CI green | PASS | M6-FULL-05 424/0, BE-UNIT-06 244/0, CONV-INT-02 58/0, WEB-UNIT-05 127/0, WEB-E2E-05 and WEB-E2E-06 54/0 (every staff-dashboard feature, desktop + tablet); CI-06 green on 6297f65 |
| Quality | Every patient and staff flow used live | PASS | LIVE-TG-01 and LIVE-TG-02 (every patient flow in Telegram, ending with /deletemydata and a database check), LIVE-DASH-01 (receptionist and admin, 26 checks) |
| Security | Threat model and security review done; no open owner actions | BLOCKED | `docs/security/threat-model.md`, `docs/security/security-review.md`. Open: BLK-05 (verify-full database TLS needs the Supabase CA file) and SEC-ROT (credentials shared in chat). The other residual risks and their status are in the security review (for example the CSP, accepted as D-42) |
| Security | No secrets in the repository (scan) | PASS | SEC-SCAN-01: 0 hits in history and tracked files; `.env` ignored (`.gitignore:2`); exposed test password rotated (ROT-01) |
| Privacy | Privacy assessment written; organisational obligations listed (no compliance claim) | NOT_STARTED | No privacy assessment exists; no retention periods are defined (GAP-30, `docs/requirements/document-analysis.md` §9–§10) |
| Data | Clinic data that patients see is consistent and confirmed | BLOCKED | Seed FAQ says open until 7 PM, `staff_hours_text` says 6 PM, and the bot used both in one chat (LIVE-TG-02). Time zone (GAP-27) and emergency number and phrases (GAP-28) not confirmed by a clinic |
| Ops | One-command start ≤ 2 min (E7-S6); fallback reply without the LLM | PASS | START-01 23.5 s, START-02 24.0 s, FRESH-02 52.7 s from a fresh clone; fallback tested with a simulated outage and seen live while the Gemini quota was used up (LIVE-TG-01) |
| Ops | Logs, health checks, backup/restore procedure documented and tested | PARTIAL | JSON logs with a request id (`test_observability.py`), `/healthz`, `/readyz`, scheduler heartbeat, `docs/operations/runbook.md`; recovery after a network outage observed (OBS-01). Not built: a backup/restore procedure |
| Docs | README, `.env.example`, API, architecture, deployment, runbooks | PARTIAL | README, `.env.example` (guarded by `test_env_example_lists_every_setting`), `docs/api/staff-api.md`, `docs/architecture/`, `docs/operations/runbook.md`. No deployment guide (the webhook option is not documented) |
| Deployment | Target per D-05 deployed and smoke-tested | PASS (laptop) | D-05: laptop run with CI, no live cloud deployment. FRESH-02 started API, bot and dashboard from a fresh GitHub clone; Docker Compose not built (D-31) |

## Blocks go-live

| ID | What | Owner |
|---|---|---|
| DEC-RT | Reply time (NFR-01) and the §3.9 booking and reschedule/cancel targets at production settings: decide D-34 option C (a faster model, a paid tier, or a separate Google Cloud project for evaluations), then rerun the evaluation with `EVAL_RUNS=2`. Note D-16: a real pilot with patient data needs the paid Gemini tier | Arman |
| BLK-05 | Install the Supabase CA certificate, set `DB_SSL_ROOT_CERT`, check its SHA-256 (verify-full TLS) | Arman |
| SEC-ROT | Rotate the database password, Gemini key and bot token shared in chat | Arman |
| HOURS | Pick 6 PM or 7 PM and edit it under Clinic answers or Clinic settings | Arman |
| GAPS | Open source gaps: GAP-02 (diagrams and "3 gates" never supplied), GAP-27 (time zone), GAP-28 (emergency number and phrases), GAP-30 (retention periods, privacy assessment) | Arman |

Closed: BLK-06 (every patient flow used live, LIVE-TG-01 and LIVE-TG-02), PR-1 (merged 2026-11-04, 97d6f86), EVAL-FINAL (AEV-PROD-06).
