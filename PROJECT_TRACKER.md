# Project Tracker — Clinic Appointment Booking Agent

Last updated: 2026-11-03 · Phase: **4 Foundation — design approved, environment verified, implementation starting**

Detailed trackers: [epics](docs/tracking/epic-tracker.md) · [stories](docs/tracking/user-story-tracker.md) · [RTM](docs/tracking/requirement-traceability-matrix.md) · [tests](docs/tracking/test-execution-tracker.md) · [bugs](docs/tracking/bug-tracker.md) · [decisions](docs/tracking/decision-log.md) · [dependencies](docs/tracking/dependency-tracker.md) · [release readiness](docs/tracking/release-readiness.md)

Status values: NOT_STARTED · ANALYSIS · READY · IN_PROGRESS · CODE_COMPLETE · TESTING · BLOCKED · FAILED · COMPLETED · DEFERRED_WITH_APPROVAL. A status is COMPLETED only with verification evidence.

## Phase status

| Phase | Status | Evidence | Outstanding |
|---|---|---|---|
| 0 Discovery | COMPLETED | Source read in full (858 lines); `docs/requirements/document-analysis.md`; extraction counts verified against the source's summary table | 2 embedded diagrams inaccessible (GAP-02) |
| 1 Product planning | COMPLETED | `requirements-inventory.md` (100 ACs + all BR/FR/NFR), trackers; D-01/02/03/05 decided by Arman | Approval of IMP-01..15 (in spec) |
| 2 Architecture | COMPLETED | `docs/architecture/*` (system, ERD, agent, API/auth), `docs/security/threat-model.md`; approved by Arman 2026-11-03 ("start the complete development") | — |
| 3 Design | NOT_STARTED | — | Needs D-01 |
| 4 Foundation | IN_PROGRESS | M1 backend built test-first on `feat/m1-foundation`: schema + migrations, seed, services, agent loop, conversation, bot, API, CI workflow. Runs ENV-01, M1-FULL (163 pass), M1-LIVE-* | Independent code review; Telegram tap-through by a person; CI run on GitHub (not pushed) |
| 5 Feature development | NOT_STARTED | — | — |
| 6 AI agent | NOT_STARTED | — | Needs D-03 |
| 7 Integration | NOT_STARTED | — | — |
| 8 QA | NOT_STARTED | — | — |
| 9 Production readiness | NOT_STARTED | — | Needs D-05 |
| 10 Final acceptance | NOT_STARTED | — | — |

## Scope summary

7 epics · 32 stories · 93 points · 20 Must / 11 Should / 1 Could · 100 acceptance criteria · plus 15 implied requirements (IMP, pending approval) and 10 master-prompt delivery requirements (MP).

| Epic | Stories | Points | Status |
|---|---|---|---|
| E1 Onboarding and consent | 4 | 8 | NOT_STARTED |
| E2 Appointment booking | 5 | 18 | NOT_STARTED |
| E3 Manage appointments | 3 | 10 | NOT_STARTED |
| E4 Reminders and notifications | 4 | 10 | NOT_STARTED |
| E5 Clinic info, safety, handoff | 4 | 11 | NOT_STARTED |
| E6 Staff dashboard | 6 | 19 | NOT_STARTED |
| E7 Platform, security, quality | 6 | 17 | NOT_STARTED |

Completion: 0 / 32 stories verified (0%) · 0 / 100 ACs verified (0%).

## Proposed roadmap (dependency-aware, follows source §5)

| Milestone | Content | Exit evidence |
|---|---|---|
| M0 Design approval | Resolve D-01..05; architecture, ERD, agent design, API contract, design system | Approved spec |
| M1 Foundation (≈ Sprint 1) | E7-S1 setup, DB schema + migrations, seed, booking service core, E7-S2 audit log, E1-S1..S3, E2-S1 | Unit + integration tests green |
| M2 Booking core (≈ Sprint 2) | E2-S2, E2-S3, E2-S4 (concurrency test), E5-S3 emergency filter | 10-parallel-booking test → exactly 1 row; Telegram booking demo |
| M3 Manage + safety (≈ Sprint 3) | E3-S1..S3, E5-S2, E2-S5 | Authorization tests; refusal scenarios |
| M4 Reminders + info (≈ Sprint 4) | E4-S1..S3, E5-S1, E5-S4, E7-S3 | Restart test, retry test |
| M5 Dashboard (≈ Sprint 5) | E6-S1..S4, E4-S4, IMP-01..05 | Role tests, E2E browser tests |
| M6 Quality + release (≈ Sprint 6) | E7-S5 evaluation suite, E1-S4, E6-S5, E7-S4, E7-S6, E6-S6 | Evaluation report meets §3.9 targets |

## Blockers

| ID | Blocker | Owner | Since |
|---|---|---|---|
| BLK-01 | ~~Design spec approval~~ Resolved 2026-11-03: Arman approved and asked to start development | Arman | 2026-11-02 |
| BLK-02 | ~~Supabase setup~~ Resolved 2026-11-03: MCP re-authenticated (stale OAuth client cleared with `claude mcp logout`); bootstrap applied; SCRAM verifiers set; pooler host `aws-1-eu-west-3.pooler.supabase.com` derived and verified by login. Optional hardening left to Arman: turn the Data API off (our schemas are already unreachable to `anon`/`authenticated`) | Arman | 2026-11-02 |
| BLK-03 | Gemini free-tier RPM/RPD limits from AI Studio. Key itself verified 2026-11-02: `check_env.py gemini` PASS, `gemini-3.5-flash-lite` available, test reply 'OK' | Arman | 2026-11-02 |
| BLK-05 | Download the Supabase CA certificate (Dashboard → Database Settings → SSL Configuration) to `infrastructure/db/prod-ca-2021.crt` and set `DB_SSL_ROOT_CERT`; compare its SHA-256 with `80:70:25:AD:…:72:E6:CA:FA` (threat model T-DB-TLS) | Arman | 2026-11-03 |
| BLK-06 | Telegram tap-through by a person (registration and doctor list) — the only M1 check automation cannot do | Arman | 2026-11-03 |
| BLK-04 | ~~Telegram bot token~~ Resolved 2026-11-02: `check_env.py telegram` PASS (bot @clinic_dev_project_bot); no webhook set, so long polling will work | Arman | 2026-11-02 |

Resolved: D-01 hybrid stack, D-02 hosted Supabase, D-03 Gemini, D-05 laptop + Compose + CI (all decided 2026-11-02).

Open risk R-LAT-01: the Supabase project is in `eu-west-3` (Paris) while the clinic is in Asia/Kolkata. Measured 2026-11-03: a warm `select 1` through the pooler takes ≈0.8 s end to end (several round trips), so every bot reply carries database latency on top of the LLM. Mitigation: production project in `ap-south-1` (Mumbai); keep round trips per message low; settings are cached 30 s.

Open risk R-DB-TLS: certificate verification is implemented (D-26) but dev runs unverified until `DB_SSL_ROOT_CERT` points to the official `prod-ca-2021.crt` from the dashboard.

Open risk R-GEM-02: Gemini free-tier latency spikes. Measured 2026-11-03 ~19:40 IST: `gemini-3.5-flash-lite` took 15–40 s per call (no tools, 19 output tokens, no thinking tokens), `gemini-3.8-flash` returned 503 'high demand'; earlier the same day calls took 1.3–3.8 s. The bot falls back to the clinic phone within the 8 s budget, so patients are never left without a reply, but bookings cannot proceed during a spike. Mitigation: paid tier for any pilot (also required by D-16), retry the live journey, and track p95 in the evaluation suite.

Open risk R-GEM-01: Gemini free-tier quotas are shown only in AI Studio. Unofficial reports suggest daily request limits low enough that one 35-scenario eval run may not fit in a day (not verified). Mitigation: check limits; use flash-lite; enable paid billing for eval runs if needed.

## Session handoff — 2026-11-02

- **Done:** full source read; requirements inventory; document analysis (39 gaps, 10 source-vs-master-prompt conflicts); trackers; decision log (D-01..D-18); architecture spec (system, ERD, agent, API/auth); threat model; platform facts verified against PyPI, npm and official docs.
- **Not done:** no code; no git repository yet (created at scaffold time); design system, privacy assessment, security architecture/checklist, API reference (later phases).
- **Next task:** Arman reviews `docs/architecture/README.md` → on approval, write the implementation plan (writing-plans) → M1 Foundation.
