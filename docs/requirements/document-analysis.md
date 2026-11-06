# Document Analysis — Clinic Appointment Booking Agent

Source: `docs/requirements/source/brd-prd-backlog.md`, a copy of `Clinic Appointment Booking Agent — BRD, PRD & Product Backlog.md` (dated Oct 28, 2026, author Arman Khan), identical except the §5.2 Status cells, set to Done on 2026-11-06 (028e0c2); no line moved. `L<n>` = line in that file. Full itemised inventory: `requirements-inventory.md`.

Sections 1–8 are the analysis of the source as written (2026-11-02). The **Status** columns in §9 and §10, and the status notes in §11–§14, were audited against the code, the migrations and the decision log on 2026-11-05 (commit 3938155). Code paths are relative to `apps/backend/src/clinic/` unless they start with `apps/`, `infrastructure/` or `scripts/`. Decisions: `docs/tracking/decision-log.md`. Several decisions (D-04, D-06..D-11, D-13..D-16, D-18) are recorded there as PROPOSED; D-22 records their approval as part of the design spec.

## 1. Coverage statement

| Item | Result |
|---|---|
| Lines read | All 858 lines, every section, every table |
| Sections | §1 Overview (1.1 Assumptions, 1.2 Glossary), §2 BRD (2.1–2.8), §3 PRD (3.1–3.9), §4 Epics E1–E7, §5 Backlog (5.1–5.3), §6 Open Questions, story count summary |
| Extracted | 5 business objectives, 10 BRs, 18 FRs, 11 NFRs, 14 agent-design rules, 8 tool contracts, 12 data-model items, 8 evaluation targets, 6 journeys, 9 scope items, 4 constraints, 7 assumptions, 7 risks, 3 success criteria, 5 planning rules, 6 stakeholders, 4 personas, 7 epics, 32 stories, **100 acceptance criteria**, 6 open questions |
| Self-consistency checks (scripted) | Story counts, P0/P1/P2 split and points per epic match the summary table for all 7 epics. All 32 stories appear in the §5.2 backlog with matching priority, points and sprint. Sprint loads 13/15/16/15/17/17 match the stated 13–17 range. No story depends on a story from a later sprint. |
| **Not accessible** | **L258** `[embedded content: system architecture · 10 components]` and **L433** `[embedded content: sprint roadmap · 6 sprints, 3 gates]` are placeholders; the diagrams are not in the file. The architecture can be rebuilt from §3.4 and §3.8 text. The "3 gates" are **not defined anywhere** in the text (only hints: "Sprint 2 ends with a working booking demo", "booking by week 4, safety by week 6"). If you have the original diagrams, please share them. |

## 2. What the product is

A **Telegram chatbot** driven by an LLM agent lets patients of **one small clinic (2–5 doctors)** register with consent, book, view, reschedule and cancel appointments at any hour, and receive reminders. Clinic staff use a **web dashboard**. The agent acts only through **eight validated tools**. The **database, not the LLM, is the source of truth** for slots and bookings. It never gives medical advice; emergencies are caught by a keyword filter **before** the LLM runs.

It is scoped as a **12-week diploma mini project for one student** (L7, A3, CON-02), using free tools (CON-01) and **synthetic data only** (A4, CON-04). It must run on a student laptop (CON-03) and be explainable in a viva (SC-03, AGT-14).

## 3. Business objectives and success criteria

| ID | Objective | Target |
|---|---|---|
| BO-1 | Patients book without calling | ≥ 90% booking scenarios end to end |
| BO-2 | No double bookings | 0 in concurrency + scenario tests |
| BO-3 | Fewer forgotten appointments | 100% eligible appointments get a reminder |
| BO-4 | Patient safety | 100% medical/emergency prompts handled per policy |
| BO-5 | Staff stay in control | 100% agent actions visible on dashboard + audit log |

Success = live Telegram demo (register → book → reminder → reschedule → cancel, each visible on the dashboard), an evaluation report meeting these targets, and a project report/viva (SC-01..03).

## 4. Stakeholders and personas

Patient (Telegram end user), Receptionist (dashboard), Doctor (owns hours and leave; **no login in the data model**, see GAP-11), Clinic admin (configuration, FAQ, audit log), Project guide/examiner (grades), Student developer (builds and presents). Personas in §3.1 add goals: book in under 2 minutes, accurate day schedule, leave that notifies patients automatically, no-show data.

## 5. Functional scope

| Area | Requirements | Stories |
|---|---|---|
| Onboarding and consent | FR-01, FR-17 | E1-S1..S4 |
| Doctors, availability, booking, double-booking prevention, relative dates | FR-02..05, FR-11 | E2-S1..S5 |
| View, reschedule, cancel with a 2-hour cut-off | FR-06 | E3-S1..S3 |
| 24h and 2h reminders, reminder buttons, clinic-side change notices | FR-07, FR-12, FR-13 | E4-S1..S4 |
| FAQ from approved content, medical refusal, emergency redirect, human handoff | FR-08, FR-14, FR-15 | E5-S1..S4 |
| Staff login, daily schedule, schedules and leave, walk-ins, attendance, metrics | FR-09, FR-16, FR-18 | E6-S1..S6 |
| Setup, audit log, rate limits, injection resilience, evaluation suite, demo packaging | FR-10 | E7-S1..S6 |

**Out of scope (L92–97):** triage or any medical advice, payments and insurance, medical records or hospital integration, video consultations, **multiple clinics**, WhatsApp/SMS/voice. E7 scope also excludes **cloud production hosting** (L762).

## 6. Non-functional scope

p95 reply ≤ 5 s (provider dependent) · no duplicate or missed reminders across restarts · secrets only in `.env` · staff passwords bcrypt/argon2 with 15-min lockout after 5 failures in 15 min · patients see only their own data · store only name, phone, Telegram ID and appointments (no health details) · chat history in memory only (last 20 messages) · 20 messages/min and 1,000-character limits · every confirmation is a tap button · pytest unit tests and an evaluation suite · structured JSON logs with a request ID.

## 7. Key workflows

1. **Message pipeline (AGT-01..06):** guardrails (emergency, rate, length) → LLM with system prompt, history and tools → Pydantic-validated tool call with patient ID injected from the Telegram session → booking service → result back to the LLM; at most 5 tool calls per message.
2. **Confirmation gate (AGT-07):** book, reschedule and cancel return a pending summary. Data is written only when the patient taps Confirm.
3. **Booking write:** transaction plus a partial unique index on `(doctor_id, start_time) WHERE status='booked'`. A losing concurrent booking gets `SLOT_TAKEN`.
4. **Reschedule:** a single transaction creates the new booking (`rescheduled_from`) and cancels the old one. If the new slot is taken, the old booking stays unchanged.
5. **Reminders:** APScheduler runs every 5 min. Each reminder is claimed via unique `(appointment_id, type)` before sending; up to 3 retries with backoff.
6. **Clinic-side change:** staff cancel a booking or add leave → affected patients are notified with a Reschedule button → after retries are exhausted, the appointment is flagged for a staff call.
7. **Emergency:** keyword match → fixed reply with the emergency number, **no LLM call** → alert on the dashboard.

## 8. Technical constraints in the source

Python 3.11+ everywhere; python-telegram-bot; FastAPI + SQLAlchemy shared by bot and dashboard; SQLite dev / PostgreSQL optional; any tool-calling LLM or Ollama; APScheduler; **Streamlit** dashboard with custom login; pytest; Docker Compose optional; **plain provider-SDK tool loop (~150 lines), LangGraph optional** (L205).

What was built differs from this list in three places, each covered by a decision: a Next.js dashboard instead of Streamlit (D-01), Supabase Postgres only with no SQLite support (D-02, D-25), and a PowerShell start script instead of Docker Compose (D-31). See §9 and `docs/architecture/README.md` ("Built versus source").

## 9. Conflicts between the source and the master execution prompt

The master prompt says to use its stack "unless the source requirements establish a justified incompatibility". These conflicts needed a decision (see `docs/tracking/decision-log.md`). The last column is the audited outcome.

| Topic | Source (BRD/PRD) | Master prompt | Proposed resolution | Status (audited 2026-11-05) |
|---|---|---|---|---|
| Scale | 12-week diploma project, 1 student, 1 clinic, synthetic data (L7, A1, A3, A4) | "Million-dollar enterprise initiative" | Production-grade **engineering quality** within the source's **functional scope**. No multi-clinic (SCP-OUT-05). | **Resolved (D-06).** Single clinic: `clinic_settings` is one row (`ck_clinic_settings_single_row`, migration 0001); no table has a clinic id. |
| Patient channel | Telegram (L7, A2, SCP-IN-01) | Implies a web frontend | Telegram, per source. Next.js (if chosen) is the **staff** dashboard. → D-04 | **Resolved (D-04).** Patients use Telegram only (`bot/telegram_app.py`, private chats only); `apps/web` is staff-only. OQ-05 (are examiners happy with Telegram?) is still unanswered. |
| Dashboard | Streamlit (L252) — "fast to build in Python" | Next.js + shadcn, premium UI (§5, §6) | → **D-01** | **Resolved (D-01); deviation from the source kept on purpose.** Next.js 16.4.4, TypeScript, Tailwind v4, shadcn/ui in `apps/web` (`apps/web/package.json`). There is no Streamlit code. |
| Agent framework | Plain SDK loop; student explains it line by line; LangGraph optional (L205) | LangGraph preferred | → **D-01** | **Resolved (D-01), as in the source.** Plain loop on the `google-genai` SDK in `agent/loop.py`; LangGraph is not a dependency (`apps/backend/pyproject.toml`). |
| Database | SQLite dev, PostgreSQL optional (L249) | Supabase/PostgreSQL + RLS | → **D-02** (no Docker or Postgres on this machine) | **Resolved (D-02, D-17, D-25); deviation from the source kept on purpose.** Hosted Supabase Postgres only, reached through the session pooler with asyncpg. SQLite is **not** supported: the schema uses a Postgres exclusion constraint and the code uses Postgres `ON CONFLICT` (migration 0001, `services/reminders.py`). RLS is enabled on every table with an app-role-only policy (defence in depth; not per-patient isolation). |
| Staff auth | Custom login on `staff_users` with an exact lockout rule (E6-S1) | Supabase Auth "where appropriate" | Custom auth: the lockout rule is specified, and patients never log in on the web | **Resolved (D-08).** argon2id passwords, server-side sessions, 5-in-15-minute lockout in `services/staff_auth.py`; Supabase Auth is not used. |
| Conversation state | In memory only, last 20 messages (NFR-07) | Checkpointing | In-memory only; no persistent checkpointer (privacy) | **Resolved (D-07).** `agent/memory.py` (last 10 exchanges, forgotten after 2 h idle) and `agent/pending.py` live in process memory; nothing is checkpointed. |
| Hosting | "Out: cloud production hosting" (L762); runs on a laptop (CON-03) | Production deployment, CI/CD, monitoring, backups | → **D-05** | **Resolved (D-05, D-31).** Laptop run with `scripts/start.ps1`, CI in `.github/workflows/ci.yml`. **Not built:** a production or cloud deployment, monitoring beyond health endpoints and JSON logs, a Docker Compose file, and a documented backup/restore procedure. |
| Compliance | Legal review outside the project; synthetic data only (L104) | Privacy assessment (DPDP Act 2023; HIPAA if applicable) | Write the docs; claim no compliance | **Open.** A threat model and a security review exist (`docs/security/`), but **no privacy assessment has been written** (the release-readiness "Privacy" gate is NOT_STARTED). No compliance is claimed anywhere. |
| Budget | Free tools, LLM free tier or local model (CON-01) | — | → **D-03** (LLM provider) | **Resolved (D-03, D-13, D-38).** Gemini free tier, default model `gemini-3.5-flash-lite` (`.env.example`). Consequence: 500 requests per day shared by the bot and the evaluation suite (QUOTA-01, acceptance report). No local-model fallback is built. |

Viva constraint: SC-03, A5 and AGT-14 expect the student to explain the agent loop, tools and guardrails. Every technology beyond the source stack adds to what must be explained.

## 10. Gaps, ambiguities and inconsistencies

Status values: **Resolved** (implemented; the evidence is cited), **Resolved (no change needed)** (an observation about the document), **Open** (not done or still needs an owner decision).

| ID | Finding | Where | Proposed handling | Status (audited 2026-11-05) |
|---|---|---|---|---|
| GAP-01 | BO section says targets are measured in "section 3.10"; evaluation is §3.9 | L46 vs L262 | Treat as §3.9 | **Resolved.** The evaluation suite and `docs/testing/acceptance-report.md` measure against §3.9. |
| GAP-02 | Architecture and roadmap diagrams missing; "3 gates" undefined | L258, L433 | Rebuild architecture from text; gates need your input or are dropped | **Partly open.** Architecture rebuilt in `docs/architecture/system-architecture.md`. The "3 gates" were never defined and no decision records them; the original diagrams were never supplied. |
| GAP-03 | §6 Open Questions sits between Epic E2 and E3; E3–E7 follow it | L482–493 | Ordering only; no content lost (all 32 stories verified) | **Resolved (no change needed).** |
| GAP-04 | E1-S1-AC1 shows Share-phone on /start, but JRN-01, E1-S3-AC1 and E1-S2-AC1 put consent first | L300 vs L139, L314, L329 | Consent first, then the Share-phone button | **Resolved (D-09).** `/start` shows the consent notice with I agree / No thanks; the Share-phone button comes only after I agree (`conversation/registration.py` `welcome_and_consent`, `ask_for_phone`; `conversation/service.py` `_consent`). A contact shared before consent restarts the consent step. |
| GAP-05 | "Marked confirmed by patient" has no field; status enum has no "confirmed" | L587 vs L233 | Add `patient_confirmed_at` (IMP-08); keep the enum and partial index unchanged | **Resolved (IMP-08).** `appointments.patient_confirmed_at` (migration 0001); set by `services/booking.py` `confirm_presence`; shown as `patient_confirmed` in the staff API. |
| GAP-06 | "Flagged on the dashboard" has no field | L602 | Add a notification-failure flag (IMP-09) | **Resolved (IMP-09).** `appointments.staff_attention_reason` / `staff_attention_at` (migration 0001), set to `notification_failed` or `reminder_failed` (`services/notifications.py`, `services/reminders.py`); listed by `GET /attention`. |
| GAP-07 | Emergency alert on the dashboard has no table | L650 | `emergency_alerts` without message text (IMP-06; NFR-06) | **Resolved (IMP-06).** Table `emergency_alerts` has no text column (migration 0001); `services/alerts.py`. |
| GAP-08 | Ticket "resolver" not in `handoff_tickets` | L665 vs L235 | Add `resolved_by`, `resolved_at` (IMP-07) | **Resolved (IMP-07).** Columns in migration 0001; set by `services/staff_ops.py` `resolve_ticket`. |
| GAP-09 | Schedules need "breaks", but the model is one start/end per weekday row | L713 vs L231 | Several non-overlapping rows per weekday | **Resolved.** Several blocks per weekday; overlap and `end <= start` are rejected (`services/admin.py` `validate_blocks`; CHECK `end_time > start_time` in migration 0001). The seed gives every doctor a lunch break. |
| GAP-10 | Walk-in patients are booked "by name and phone", but `telegram_user_id` is assumed; their consent is unspecified | L727 vs L229 | Nullable `telegram_user_id`; link on later Telegram registration with the same phone; staff record verbal consent (IMP-14) | **Resolved (IMP-14).** `patients.telegram_user_id` is nullable; staff bookings need `verbal_consent: true` and store `consent_source = 'staff_verbal'` (`services/staff_ops.py`); a later Telegram registration with the same phone links the record (`services/patients.py`). |
| GAP-11 | Doctor is a stakeholder, persona and E6 target user, but `staff_users.role` has only receptionist/admin | L61, L134, L672 vs L237 | No doctor login in the MVP; admin manages doctor hours and leave | **Resolved (design approved, D-22).** Roles are `receptionist` and `admin` only (CHECK `ck_staff_users_role`); there is no doctor login. |
| GAP-12 | No stories for managing doctors, an FAQ editor, staff accounts or an audit-log viewer, though ACs rely on them | E2-S1-AC2, E5-S1-AC3, E6-S1-AC4, E7-S2-AC3 | IMP-01..04 | **Resolved (D-11).** All four exist as admin API routes and dashboard screens (see IMP-01..04 in `requirements-inventory.md` §14). |
| GAP-13 | Where clinic settings live (name, phone, address, hours, time zone, emergency number and phrases, cut-off, window, limits) is unspecified | A7, L32, L648 | IMP-05: a settings table edited by admin, with env defaults | **Resolved (IMP-05), with one difference.** Single-row `clinic_settings` table, edited through `PATCH /settings`. Defaults come from the seed script (`apps/backend/scripts/seed.py`), not from `.env`; only the time zone is read from `.env` (`CLINIC_TIMEZONE`). |
| GAP-14 | `part_of_day` boundaries undefined | FR-03, L195 | morning < 12:00 ≤ afternoon < 17:00 ≤ evening (configurable) | **Resolved.** `domain/slots.py` `part_of_day`; boundaries are the settings `morning_end` (12:00) and `afternoon_end` (17:00). |
| GAP-15 | "Near a month end" and "next Monday" are undefined | L424 | Deterministic resolver; exact rules in the design spec | **Resolved.** Rules are in `domain/dates.py`: `next <weekday>` is the first one strictly after today; a bare day of month in the last 7 days of a month returns `AMBIGUOUS_DATE`. |
| GAP-16 | Seed "2 weeks of schedules" vs a weekly-pattern schedule model | L775 vs L231 | Weekly patterns + 2 weeks of synthetic appointments | **Resolved.** The seed writes weekly patterns plus appointments for the past 7 and next 7 days (`apps/backend/scripts/seed.py`). |
| GAP-17 | Pending confirmations live in memory (NFR-07); a Confirm tap after a restart has nothing to confirm | L217, L180 | A stale Confirm fails safely and asks the patient to retry | **Resolved.** An unknown or expired token gets "This request has expired, please ask again." and writes nothing (`conversation/service.py`, `agent/pending.py`; pending actions expire after 10 minutes). |
| GAP-18 | Audit covers agent tool calls only; staff writes, logins and FAQ edits are not covered | FR-10, L787 vs BO-5 | Recommend auditing staff actions too (REC) | **Resolved.** Staff writes, logins, lockouts and logouts are audited with `actor_type = 'staff'` (`services/staff_ops.py`, `services/admin.py`, `services/staff_auth.py`). |
| GAP-19 | Behaviour when a reminder fails after 3 retries, and 2h reminders for bookings made < 2h ahead, are unspecified | L562, L574 | Log + flag; 2h reminder is sent if booked ≥ 2h ahead, else skipped | **Resolved.** After the first attempt plus 3 retries the reminder is `failed`, logged, and the appointment is flagged `reminder_failed`; a 2h reminder for a booking made less than 2 h ahead is recorded as `skipped` (`services/reminders.py`). |
| GAP-20 | Per-patient limits (1/doctor/day, 3 upcoming) during reschedule are unspecified | L395, L524 | Exclude the appointment being moved | **Resolved.** `precheck(..., exclude_appointment_id=...)` in `agent/tools.py` `reschedule_appointment` and `services/booking.py`. |
| GAP-21 | Does the cut-off bind staff? Glossary says "the bot cannot" | L32 | Bot only; staff are not bound | **Resolved.** Staff cancellation has no cut-off check (`services/staff_ops.py` `cancel`); the bot path checks it (`domain/appointments.py` `within_cutoff`). |
| GAP-22 | Can attendance marks be corrected? Status transitions are not fully defined | L741 | State machine IMP-15; admin may correct completed ↔ no_show | **Resolved (IMP-15).** `domain/appointments.py` `can_transition`; a receptionist changing an existing mark gets 403. |
| GAP-23 | Sliding 15-minute failure window needs a first-failure timestamp | L686 vs L237 | Add `first_failed_at` | **Resolved.** `staff_users.first_failed_at` (migration 0001); the same columns exist for unknown usernames in `login_failures` (migration 0003). |
| GAP-24 | No-show rate denominator undefined | L754 | no_show / (completed + no_show); 0 when the denominator is 0 | **Resolved.** `services/admin.py` `weekly_metrics`. |
| GAP-25 | Deletion anonymizes name and phone, but AC3 ("treated as new user") also needs `telegram_user_id` cleared | L344–345 | Clear it too; keep anonymized appointment rows | **Resolved.** `services/patients.py` sets `full_name = 'Deleted patient'`, clears phone and Telegram ID; CHECK `ck_patients_deleted_anonymised` (migration 0002) enforces it. |
| GAP-26 | Rate-limit state is per process | L801 | Single bot instance in the MVP; documented | **Resolved (accepted limitation, D-07).** `agent/rate_limit.py` is in memory; one bot process is assumed. |
| GAP-27 | Default time zone unspecified | A7 | Configurable; seed default `Asia/Kolkata` (to be confirmed) | **Partly open.** Configurable (`CLINIC_TIMEZONE`, `.env.example` default `Asia/Kolkata`; admin-editable `timezone`). No real clinic has confirmed it and no decision records it. |
| GAP-28 | Default emergency number and phrase list unspecified | L648 | Configurable; seed `112` (India) + listed phrases; the clinic must confirm | **Partly open.** The seed sets `112` and 8 phrases (`apps/backend/scripts/seed.py`); admin-editable. No clinic has confirmed them. |
| GAP-29 | LLM provider undecided; p95 ≤ 5 s depends on it | OQ-03, L211 | → D-03 | **Resolved (D-03).** Gemini. NFR-01 (p95 ≤ 5 s) is **not met** on the dev PC (acceptance report). |
| GAP-30 | No retention periods (cancelled appointments, tickets, audit log, alerts) | — | Privacy assessment proposes them; needs owner approval | **Open.** No privacy assessment exists and no retention period is defined or enforced. The only time-based deletion is of unknown-username lockout rows after 1 day (`services/staff_auth.py`). |
| GAP-31 | Does a rescheduled booking get a new reference? | L524 | Yes, new row and new ref; the reply shows both | **Resolved.** New row with `rescheduled_from`; the reply names the old and the new reference (`conversation/appointment_actions.py`). |
| GAP-32 | "Fails the same task 3 times" undefined | L664, L188 | 3 consecutive error results for the same tool in one conversation | **Resolved.** Three consecutive results of `INVALID_ARGS`, `ERROR`, `NOT_FOUND`, `SLOT_UNAVAILABLE` or `INVALID_DATE` from one tool add a "Talk to staff" button (`conversation/service.py` `FAILURE_CODES`). The counter is per Telegram user, in memory. |
| GAP-33 | "Next 3 dates with free slots": which doctor or part of day? | L378 | Same doctor, within the booking window, any part of day | **Resolved.** `services/availability.py` (`next_days_with_slots(..., 3)`). |
| GAP-34 | "Nearest free slots" count undefined | L394 | Up to 3, same doctor, closest in time | **Resolved.** `services/booking.py` `ALTERNATIVES = 3`. |
| GAP-35 | Booking window inclusivity and minimum lead time unspecified | L379 | Today..today+30 inclusive in the clinic time zone; slot must start after now | **Resolved.** `domain/slots.py` `booking_window` (inclusive) and `free_slots` (`slot.start > now`). |
| GAP-36 | Relative dates: resolved by the LLM or by code? | L423 | Code (deterministic tool); the LLM passes the phrase | **Resolved.** `check_availability` resolves the phrase with `domain/dates.py`. |
| GAP-37 | E1-S1-AC2 "any message → greets by first name": on every message? | L301 | On the first message of a session only | **Resolved.** A session starts after 2 h of silence (`agent/memory.py` `SessionTracker`). |
| GAP-38 | "Staff hours" shared on handoff is not in the data model | L664 | Part of clinic settings (IMP-05) | **Resolved.** `clinic_settings.staff_hours_text`, returned by `handoff_to_staff`. |
| GAP-39 | If the scheduler was down until < 2h before, should the 24h reminder still go? | L559 | Send only the most specific reminder due; never both at once | **Resolved.** Inside the 2-hour window an unsent 24h reminder is recorded as `skipped` (`services/reminders.py` `decide`). |

## 11. Assumptions (source) and working assumptions (added)

Source: A1–A7 (see inventory). Added, pending your confirmation: Telegram is the only patient channel; English only; data is synthetic; single instance of the bot and scheduler; one clinic time zone.

Status (2026-11-05): Telegram only (D-04), synthetic data (seed patients use fictional `+1 202-555-01xx` numbers and no Telegram IDs), one bot process (D-07) and one clinic time zone all hold in the code. **"English only" holds only partly:** every fixed message written by code (consent, registration, emergency reply, summaries, reminders) is English, but the system prompt tells the model to "Reply ... in the patient's language" (`agent/prompt.py`), and evaluation scenario BK-07 is a Hinglish request. No decision records this change from A6.

## 12. Risks

| Risk | Impact | Mitigation | Status (2026-11-05) |
|---|---|---|---|
| Source risks RSK-01..07 (hallucinated slots, double booking, medical advice, prompt injection, LLM outage, scope creep, real data) | See L110–116 | Carried into the design and tests as written | Mitigations built: grounding guard, confirmation gate, partial unique index + exclusion constraint, emergency filter before the model, session-scoped patient ID, fallback reply. "Optional local model" (RSK-05) is not built. |
| Telegram bot token and LLM API key are external prerequisites | Cannot run E2E or the evaluation suite | You create the bot via @BotFather and provide keys in `.env` | Provided (ENV-01 in the test-execution tracker). Every patient flow was used live in Telegram on 2026-11-05 (LIVE-TG-01, LIVE-TG-02), which closed BLK-06 (updated 2026-11-06). |
| No Docker or PostgreSQL on this machine | Integration and concurrency tests cannot run on Postgres | → D-02 | Resolved: tests run on the `clinic_test` schema of the hosted Supabase project (D-17); CI uses a `postgres:17` container. |
| Python 3.14.3 installed; some libraries may lack 3.14 wheels | Install failures | Pin Python via uv after checking wheel availability (decided at scaffold time) | Resolved (D-14): `requires-python = ">=3.14"`, dependencies locked in `uv.lock`. |
| LLM non-determinism vs 90%/100% targets | Flaky evaluation | Repeated runs, fixed temperature, report variance | Partly done: temperature 0.2 (`agent/llm.py`) and `EVAL_RUNS=N` exist, but every recorded run used one repeat, so variance is **not measured** (acceptance report). |
| Master-prompt scope (enterprise, cloud, LangGraph, Supabase) exceeds the source | Larger build; more for the student to explain | D-01, D-05 | Resolved by D-01 (no LangGraph) and D-05 (no cloud). |
| Telegram long polling works locally; webhooks need public HTTPS | Production mode differs from the demo | Polling for demo; webhook option documented | Polling is built (D-18, `bot/__main__.py`). **The webhook option is not documented**: there is no deployment guide in the repository. |

## 13. Clarification questions

Blocking (asked now): **D-01** stack profile, **D-02** database host, **D-03** LLM provider, **D-05** deployment target.
Non-blocking (from source §6, for the student and guide): OQ-01 syllabus/report format, OQ-02 dates, OQ-04 partner clinic, OQ-05 Telegram acceptable to examiners, OQ-06 team size.

Status (2026-11-05): D-01, D-02, D-03 and D-05 are DECIDED in the decision log. OQ-03 is answered by D-03. OQ-01, OQ-02, OQ-04, OQ-05 and OQ-06 have no recorded answer.

## 14. Recommendations

1. Keep the source's functional scope and safety architecture exactly; they are well specified and testable.
2. Use deterministic code for anything the BRD calls safety-critical: emergency filter, confirmation gate, patient-ID injection, slot computation, relative-date resolution, limits, cut-off.
3. Add IMP-01..15 (needed to satisfy original ACs) and log each as derived.
4. Audit staff actions as well as agent tool calls (beyond FR-10).
5. Use Postgres for development and tests even if SQLite remains supported, so the concurrency test (E2-S4-AC4) exercises real row locking.

Status (2026-11-05): 1–4 were followed (D-10, D-11, GAP-18 above). For 5, Postgres is used everywhere and SQLite was **not** kept: the code and schema are Postgres-only (§9, "Database").
