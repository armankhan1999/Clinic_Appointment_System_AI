# Project Tracker — Clinic Appointment Booking Agent

Last updated: 2026-11-06 01:10 IST · Phase: **10 Final acceptance: all 32 stories COMPLETED and the final evaluation run (AEV-PROD-06); go-live waits on owner actions (DEC-RT / NFR-01, BLK-05, SEC-ROT, clinic hours)**

Detailed trackers: [epics](docs/tracking/epic-tracker.md) · [stories](docs/tracking/user-story-tracker.md) · [RTM](docs/tracking/requirement-traceability-matrix.md) · [tests](docs/tracking/test-execution-tracker.md) · [bugs](docs/tracking/bug-tracker.md) · [decisions](docs/tracking/decision-log.md) · [acceptance report](docs/testing/acceptance-report.md) · [security review](docs/security/security-review.md)

Status values: NOT_STARTED · ANALYSIS · READY · IN_PROGRESS · CODE_COMPLETE · TESTING · BLOCKED · FAILED · COMPLETED · DEFERRED_WITH_APPROVAL. A status is COMPLETED only with verification evidence.

## Phase status

| Phase | Status | Evidence | Outstanding |
|---|---|---|---|
| 0 Discovery | COMPLETED | `docs/requirements/document-analysis.md`, inventory | 2 embedded diagrams inaccessible (GAP-02) |
| 1 Product planning | COMPLETED | requirements inventory, trackers, D-01..D-05 | — |
| 2 Architecture | COMPLETED | `docs/architecture/*`, threat model; approved 2026-11-03 | — |
| 3 Design | COMPLETED | `docs/design/design-system.md`, `docs/api/staff-api.md` | — |
| 4 Foundation | COMPLETED | schema + migrations 0001–0003, seed, services, CI workflow | — |
| 5 Feature development | COMPLETED | bot, booking, manage, reminders, FAQ, handoff, staff API, dashboard | — |
| 6 AI agent | COMPLETED | tool loop, grounding guard, emergency filter, evaluation suite (38 scenarios: 35 of §3.9 + XA-01..03) | Reply-time decision (DEC-RT, below) |
| 7 Integration | COMPLETED | WEB-E2E-06 (54/54 on the live :3100 stack, every staff-dashboard feature, desktop + tablet), KEEPALIVE-01, START-01/02 | — |
| 8 QA | COMPLETED | M6-FULL-05 424/0, BE-UNIT-06 244/0, CONV-INT-02 58/0, WEB-UNIT-05 127/0, WEB-E2E-05 and WEB-E2E-06 54/0; live: LIVE-TG-01, LIVE-TG-02 (every patient flow in Telegram), LIVE-DASH-01 (receptionist + admin); AEV-PROD-06 31/38 at production settings (all 7 failures are per-call model timeouts); CI-06 green on 6297f65 | — (NFR-01 and the `EVAL_RUNS=2` rerun are tracked under DEC-RT) |
| 9 Production readiness | TESTING | security review, secret scan, `.env.example` test, one-command start, fresh-clone run, KEEPALIVE-01, ROT-01 | BLK-05 TLS CA; SEC-ROT credential rotation; DEC-RT reply time (NFR-01 not met) |
| 10 Final acceptance | IN_PROGRESS | `docs/testing/acceptance-report.md`, `docs/tracking/release-readiness.md` | Owner decisions: DEC-RT (D-34 option C), clinic hours (6 PM or 7 PM), open source gaps GAP-02/27/28/30 |

## Scope summary

7 epics · 32 stories · 93 points · 100 acceptance criteria.

**32 / 32 stories COMPLETED** (verified 2026-11-05). The last one, E2-S1, closed when XA-01 (E2-S1-AC3: an unknown specialty is reported and no doctor is invented) passed at production settings in AEV-PROD-06; the `answered` check means a fallback reply cannot pass. All 7 epics COMPLETED. Details in the story tracker and RTM.

Not met: **NFR-01** (reply ≤ 5 s for 95%): p95 20.3 s in AEV-PROD-06. **§3.9 at production settings** (AEV-PROD-06, 31/38): booking 4/8 and reschedule/cancel 5/6 are below the 90% target; every other category is met. The gap is explained in the acceptance report as E7-S5-AC3 allows: all 7 failures are one model call over the 8 s per-call timeout (`llm_unavailable error=TimeoutError` ×7; no 503, no turn budget exhausted).

## Branches

- `main` is the only branch, locally and on GitHub (`armankhan1999/Clinic_Appointment_System_AI`); every finished change is merged into it and pushed (D-35).
- PR #1 (`feat/m6-quality-e2e`) was merged on 2026-11-04 (97d6f86) and its branch deleted.
- Latest CI on `main` is green: CI-06 recorded 6297f65 green after two red runs that commit fixed.

## Blockers and owner actions

| ID | Item | Owner | Since |
|---|---|---|---|
| DEC-RT | Reply time: option A done (D-34, 8 s per call / 25 s per turn + typing status) removed all turn-budget failures. Final run AEV-PROD-06: 31/38, all 7 failures single free-tier model calls over 8 s; p95 20.3 s, so NFR-01 is not met. Next: decide D-34 option C (faster model, paid tier, or a separate Google Cloud project for evaluations), then rerun the evaluation with `EVAL_RUNS=2`; co-location (B) for the 3.9 s of database time | Arman | 2026-11-04 |
| BLK-05 | Download the Supabase CA certificate to `infrastructure/db/prod-ca-2021.crt`, set `DB_SSL_ROOT_CERT`, compare its SHA-256 with `80:70:25:AD:…:72:E6:CA:FA` | Arman | 2026-11-03 |
| ~~BLK-06~~ | Closed 2026-11-05: every patient flow used live in Telegram (LIVE-TG-01, LIVE-TG-02) | — | 2026-11-03 |
| SEC-ROT | Rotate the database password, Gemini key and bot token that were shared in chat | Arman | 2026-11-03 |
| D-33 | ~~`cn@0.5.2`~~ Resolved: replaced by `clsx` 2.1.1 + `tailwind-merge` 3.7.0 | — | 2026-11-04 |
| ~~PR-1~~ | Done: PR #1 merged on 2026-11-04 (97d6f86), branch deleted; `main` is the only branch | — | 2026-11-04 |
| QUOTA | Gemini free tier: 500 requests/day per model (QUOTA-01, verified from the API's 429), shared by the live bot and the evaluation suite; used up on 2026-11-04 by evaluation runs, and AEV-PROD-06 ran with `EVAL_RUNS=1` to stay inside it. Use a separate Google Cloud project for evaluations (limits are per project, not per key) or a paid tier; `gemini-3.5-flash` allows only 20/day (QUOTA-02, D-38). Part of the DEC-RT decision | Arman | 2026-11-04 |
| ~~EVAL-FINAL~~ | Done: AEV-PROD-06 (2026-11-05), 38 scenarios at production settings, 31/38 ([report](docs/testing/eval-2026-11-05-production-final.md)). The `EVAL_RUNS=2` rerun moves to DEC-RT | — | 2026-11-04 |
| HOURS | Clinic hours conflict in the data: the seed FAQ says open until 7 PM, `staff_hours_text` says 6 PM, and the bot used both in one chat (LIVE-TG-02). Pick one and edit it under Clinic answers or Clinic settings | Arman | 2026-11-05 |

Resolved: BLK-01 design approval, BLK-02 Supabase setup, BLK-03 Gemini limits (QUOTA-01), BLK-04 Telegram token, BLK-06 live Telegram use, PR-1, EVAL-FINAL.

## Risks

| ID | Risk | Measured | Mitigation |
|---|---|---|---|
| R-LAT-01 | Database in `eu-west-3`, clinic in India | 128 ms per round trip; median 3.9 s of each agent turn; staff booking ≈ 6 s (DB-LAT-01) | Run API/bot next to the database or move the project to `ap-south-1` |
| R-GEM-02 | Free-tier model latency | median 5.5–5.7 s per turn (2026-11-04); on 2026-11-05 about 6–7 s per Gemini call (three timed probes of 9–10 s including ≈2–3 s Python start-up) and 7 per-call timeouts in AEV-PROD-06 | Faster or paid tier (D-34 option C); per-call timeout keeps the fallback within 10 s; a 5xx is retried once (D-50); a staged summary is shown when the model fails (D-51) |
| R-DB-TLS | Dev runs use unverified TLS until BLK-05 | `db_tls_unverified` warning on start | BLK-05 |
| R-GEM-01 | Free-tier quota | **Materialised 2026-11-04**: 500 requests/day per model; HTTP 429 from ~17:45 UTC (QUOTA-01) | Separate evaluation project/key; paid tier for the live bot |

## Session handoff — 2026-11-04

- **Done:** staff API (daily + admin) and the dashboard merged; independent review of the dashboard (5 medium, 5 low) fixed test-first; secret scan and first push to GitHub; one-command start/stop; E2E on the live stack with clean console/network assertions; evaluation suite run (diagnostic 35/35, production budget 20/35) with every failure explained; traceability gaps closed with tests; final regression 414/0.
- **Not done:** decisions and owner actions above; repeated evaluation runs for variance (`EVAL_RUNS`); Docker Compose (not verifiable here, D-31).
- **Next task:** after the Gemini quota resets (≈13:30 IST 2026-11-05) run the final 38-scenario evaluation at production settings (`uv run python -m pytest -m eval tests/integration/test_agent_eval.py` in apps/backend) to close E2-S1-AC3 and record the final §3.9 figures; then BLK-05, BLK-06 and credential rotation (owner).

## Session log — 2026-11-05 (early morning)

- Live project running for Arman: `scripts/start.ps1 -WebPort 3100 -Dev` (dashboard http://localhost:3100 via `next dev`; API 127.0.0.1:8010; Telegram bot). Dev admin `owner` created; password in git-ignored `logs/dashboard-login.txt`.
- Merged to main: live development mode + `restart.ps1` (D-39), clinic date from the API (D-40), phone lookup by POST (D-41), CSP decision (D-42). All branches merged; `main` is the only branch.
- Verified: M6-FULL-04 419/0, WEB-UNIT 120/0, E2E 18/18 (production build and dev server), booking E2E 2/2 after D-41.
- Blocked: final evaluation (HTTP 429, free tier 500/day on flash-lite; 20/day on 3.5-flash).

## Session log — 2026-11-05 (live persona tests)

- Live tests on the running stack: Patient in Telegram (LIVE-TG-01, 19 checks), Receptionist and Admin in the dashboard (LIVE-DASH-01, 26 checks). AI flows deferred: the Gemini quota resets ≈13:30 IST.
- Defects found live and fixed test-first, merged to main with green CI: D-43 booking-limit reason, D-44 taken username 409, D-45 password-reset control, D-46 dialogs scroll on short screens, D-47 "No reminders: not on Telegram", leave checkbox wording.
- Doc alignment pass merged (requirements, architecture, API, security, design, READMEs).
- Mistake: the Playwright tool echoed one login snippet, exposing the e2e_desk test password in the session log; it is rotated after the E2E agent finishes. Later logins used a one-shot localhost credential server instead.
- E2E agent merged (3ac40a1): every staff-dashboard feature now has a Playwright spec (54 tests, desktop + tablet), patient-side fixtures with a marked clean-up, leave reason required (D-49). Its report led to D-48 (API keep-alive).
- Verified on merged main: WEB-UNIT-05 127/0, BE-UNIT-05 237/0, M6-FULL-05 424/0, KEEPALIVE-01; e2e_desk password rotated (ROT-01).
- Left for Arman to decide: 19 "Playwright Walkin" patients from older booking-spec runs remain in the dev database (`tests/e2e_support/cleanup.py --patient <id>` removes marked rows only).

## Session log — 2026-11-05 (evening, AI chat live)

- WEB-E2E-06: the full dashboard suite passed 54/54 on the live :3100 stack (an earlier attempt was invalidated by the PC sleeping; its leftover schedule block was reverted). Marked test rows deleted with the clean-up script (19 patients, 1 doctor), as approved.
- LIVE-TG-02: all AI-driven patient flows passed live, ending with /deletemydata (Arman's data anonymised). Fixes D-50..D-53 merged with tests. Diagnostic budgets 15/45 were used for part of the run and removed afterwards (production 8/25 confirmed).
- For Arman to decide: the seed FAQ says the clinic is open until 7 PM, but `staff_hours_text` says 6 PM; the bot used both in the same chat. Pick one and edit it under Clinic answers or Clinic settings.
- Watch: the PC enters Modern Standby when idle, which stops long runs and breaks database connections until they reconnect (the stack recovered by itself within ≈15 s after each wake).
- AEV-PROD-06 (final evaluation, production settings): 31/38; every safety category 100%; XA-01 passed, which closes E2-S1-AC3; the 7 failures are all model calls over the 8 s timeout, so booking (4/8) and reschedule/cancel (5/6) stay below the §3.9 target of 90% on latency. (Corrected 2026-11-06: this line first said "E2-S1-AC3 stays open", which confused the no-invented-doctor criterion with the booking target.) CI-06: two red runs from a test-typing slip, fixed in 6297f65.
- Clean-up: Dr. Live Test, Dr. Live Test Two and the live_reset_test account deactivated (reversible). The walk-ins "Live Walkin One/Two" remain (not test-marked).
- **Next task:** Arman decides D-34 option C (faster model, paid tier or separate project) and the 6 PM / 7 PM hours; then rerun the evaluation with `EVAL_RUNS=2`; owner actions BLK-05 and credential rotation.

## Session log — 2026-11-06 (status documents)

- Status documents aligned with AEV-PROD-06 and the live tests (story, epic and RTM trackers, acceptance report, README, requirement and security notes); the bug tracker now lists the defects recorded in the decision log, the run log and the fix commits; release readiness is a current checklist. No code, test, migration, seed or configuration change.
- **Next task:** unchanged from the evening log above.
