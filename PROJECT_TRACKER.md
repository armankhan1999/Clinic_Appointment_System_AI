# Project Tracker — Clinic Appointment Booking Agent

Last updated: 2026-11-05 03:30 IST · Phase: **10 Final acceptance: application complete except the final model evaluation (Gemini daily quota) and owner actions**

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
| 6 AI agent | COMPLETED | tool loop, grounding guard, emergency filter, evaluation suite (35 scenarios) | Reply-time decision (below) |
| 7 Integration | COMPLETED | WEB-E2E-02 (18/18 on the live stack), START-01/02 | — |
| 8 QA | TESTING | M6-FULL-02 414/0, WEB-UNIT-02 116/0, AEV-DIAG-03 35/35, AEV-PROD-01 14/35 and AEV-PROD-02 19/35 (genuine passes after the D-36 recount) | Telegram tap-through by a person (BLK-06); CI re-run on GitHub |
| 9 Production readiness | TESTING | security review, secret scan, `.env.example` test, one-command start, fresh-clone run | BLK-05 TLS CA; credential rotation; reply-time decision |
| 10 Final acceptance | IN_PROGRESS | `docs/testing/acceptance-report.md` | Owner decisions listed there |

## Scope summary

7 epics · 32 stories · 93 points · 100 acceptance criteria.

**31 / 32 stories COMPLETED** (verified 2026-11-04 evening), 1 TESTING: E2-S1 (AC3 'no invented doctor' has no genuine evaluation pass yet; XA-01 only passed on a fallback, then the Gemini quota ran out). Epics E1, E3–E7 COMPLETED; E2 TESTING. NFR-01 not met on this PC. Details in the story tracker and RTM.

## Branches

- `main` on GitHub (`armankhan1999/Clinic_Appointment_System_AI`) = 00dac72 (pushed 2026-11-04, D-28). Its CI run 41797730819 failed 4 TLS unit tests (CI-01); the fix is on the feature branch.
- `feat/m6-quality-e2e` → PR #1 (https://github.com/armankhan1999/Clinic_Appointment_System_AI/pull/1): review fixes, evaluation suite results, E2E hardening, packaging, CI web job, traceability gaps, D-33, D-34. CI green on the PR (CI-02).

## Blockers and owner actions

| ID | Item | Owner | Since |
|---|---|---|---|
| DEC-RT | Reply time: option A done (D-34, 8 s per call / 25 s per turn + typing status) removed all turn-budget failures; the remaining 14/35 are single free-tier model calls over 8 s (AEV-PROD-02). Next lever: faster or paid model tier (option C); co-location (B) for the 3.9 s of database time | Arman | 2026-11-04 |
| BLK-05 | Download the Supabase CA certificate to `infrastructure/db/prod-ca-2021.crt`, set `DB_SSL_ROOT_CERT`, compare its SHA-256 with `80:70:25:AD:…:72:E6:CA:FA` | Arman | 2026-11-03 |
| BLK-06 | Telegram tap-through: registration, reminders, buttons and notices done live 2026-11-05 (LIVE-TG-01); booking by chat waits for the Gemini quota | Claude / Arman | 2026-11-03 |
| SEC-ROT | Rotate the database password, Gemini key and bot token that were shared in chat | Arman | 2026-11-03 |
| D-33 | ~~`cn@0.5.2`~~ Resolved: replaced by `clsx` 2.1.1 + `tailwind-merge` 3.7.0 | — | 2026-11-04 |
| PR-1 | Review and merge PR #1 (`feat/m6-quality-e2e` → `main`); CI green on the PR | Arman | 2026-11-04 |
| QUOTA | Gemini free tier: 500 requests/day per model (QUOTA-01, verified from the API's 429), shared by the live bot and the evaluation suite; used up on 2026-11-04 by evaluation runs. Use a separate Google Cloud project for evaluations (limits are per project, not per key) or a paid tier; `gemini-3.5-flash` allows only 20/day (QUOTA-02, D-38) | Arman | 2026-11-04 |
| EVAL-FINAL | Final 38-scenario evaluation at production settings (`EVAL_RUNS=2`) after the quota resets (~13:30 IST 2026-11-05) | Claude | 2026-11-04 |

Resolved: BLK-01 design approval, BLK-02 Supabase setup, BLK-03 Gemini limits (QUOTA-01), BLK-04 Telegram token.

## Risks

| ID | Risk | Measured | Mitigation |
|---|---|---|---|
| R-LAT-01 | Database in `eu-west-3`, clinic in India | 128 ms per round trip; median 3.9 s of each agent turn; staff booking ≈ 6 s (DB-LAT-01) | Run API/bot next to the database or move the project to `ap-south-1` |
| R-GEM-02 | Free-tier model latency | median 5.5–5.7 s per turn; spikes past 8 s per call | Faster or paid tier; per-call timeout keeps the fallback within 10 s |
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
