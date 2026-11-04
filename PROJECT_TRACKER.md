# Project Tracker — Clinic Appointment Booking Agent

Last updated: 2026-11-04 · Phase: **8 QA / 10 Final acceptance — built and tested; go-live decisions pending**

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
| 8 QA | TESTING | M6-FULL-02 414/0, WEB-UNIT-02 116/0, AEV-DIAG-03 35/35, AEV-PROD-01 20/35 | Telegram tap-through by a person (BLK-06); CI re-run on GitHub |
| 9 Production readiness | TESTING | security review, secret scan, `.env.example` test, one-command start, fresh-clone run | BLK-05 TLS CA; credential rotation; reply-time decision |
| 10 Final acceptance | IN_PROGRESS | `docs/testing/acceptance-report.md` | Owner decisions listed there |

## Scope summary

7 epics · 32 stories · 93 points · 100 acceptance criteria.

**26 / 32 stories COMPLETED** (verified 2026-11-04), 6 TESTING. Epics E1, E3, E4, E6 COMPLETED; E2, E5, E7 TESTING. Open evidence gaps: E2-S1-AC3, E2-S2-AC4, E2-S5-AC1, E5-S1-AC1, E5-S2-AC1 (partly), E7-S1-AC1 (database bootstrap from a clean clone); NFR-01 not met on this PC. Details in the story tracker and RTM.

## Branches

- `main` on GitHub (`armankhan1999/Clinic_Appointment_System_AI`) = 00dac72 (pushed 2026-11-04, D-28). Its CI run 41797730819 failed 4 TLS unit tests (CI-01); the fix is on the feature branch.
- `feat/m6-quality-e2e` (local, not pushed): review fixes, evaluation suite results, E2E hardening, packaging, CI web job, traceability gaps.

## Blockers and owner actions

| ID | Item | Owner | Since |
|---|---|---|---|
| DEC-RT | Reply time: production 8 s budget gives 20/35 on this PC (all 15 failures are timeouts, no wrong answers); 35/35 with time. Choose: longer whole-turn budget with 8 s per model call, co-locate API/bot with the database, faster model tier (acceptance report) | Arman | 2026-11-04 |
| BLK-05 | Download the Supabase CA certificate to `infrastructure/db/prod-ca-2021.crt`, set `DB_SSL_ROOT_CERT`, compare its SHA-256 with `80:70:25:AD:…:72:E6:CA:FA` | Arman | 2026-11-03 |
| BLK-06 | Telegram tap-through by a person (registration, booking, reminders) | Arman | 2026-11-03 |
| SEC-ROT | Rotate the database password, Gemini key and bot token that were shared in chat | Arman | 2026-11-03 |
| D-33 | Keep `cn@0.5.2` or switch to `clsx` + `tailwind-merge` | Arman | 2026-11-04 |
| PUSH | Approve pushing `feat/m6-quality-e2e` (re-runs CI with the fix) | Arman | 2026-11-04 |
| BLK-03 | Gemini free-tier RPM/RPD limits (AI Studio) | Arman | 2026-11-02 |

Resolved: BLK-01 design approval, BLK-02 Supabase setup, BLK-04 Telegram token.

## Risks

| ID | Risk | Measured | Mitigation |
|---|---|---|---|
| R-LAT-01 | Database in `eu-west-3`, clinic in India | 128 ms per round trip; median 3.9 s of each agent turn; staff booking ≈ 6 s (DB-LAT-01) | Run API/bot next to the database or move the project to `ap-south-1` |
| R-GEM-02 | Free-tier model latency | median 5.5–5.7 s per turn; spikes past 8 s per call | Faster or paid tier; per-call timeout keeps the fallback within 10 s |
| R-DB-TLS | Dev runs use unverified TLS until BLK-05 | `db_tls_unverified` warning on start | BLK-05 |
| R-GEM-01 | Free-tier quotas unknown | Three full evaluation runs fit in one day on 2026-11-04 (not a quota measurement) | Check AI Studio limits |

## Session handoff — 2026-11-04

- **Done:** staff API (daily + admin) and the dashboard merged; independent review of the dashboard (5 medium, 5 low) fixed test-first; secret scan and first push to GitHub; one-command start/stop; E2E on the live stack with clean console/network assertions; evaluation suite run (diagnostic 35/35, production budget 20/35) with every failure explained; traceability gaps closed with tests; final regression 414/0.
- **Not done:** decisions and owner actions above; repeated evaluation runs for variance (`EVAL_RUNS`); Docker Compose (not verifiable here, D-31).
- **Next task:** owner decision on reply time → implement it → re-run AEV at the production budget → push and confirm CI green.
