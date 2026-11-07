# Clinic Appointment Booking Agent: High-Level and Low-Level Design (as built)

This document describes the system **exactly as it is implemented** in this repository. Every statement was
checked against the source code at commit `97ccc23` (8 November 2026). Where a design document elsewhere in
`docs/` says something different, the code wins and this document follows the code.

- Path shorthand: `clinic/...` means `apps/backend/src/clinic/...`; `web/...` means `apps/web/...`.
- References such as `clinic/services/booking.py:197` point to the line where the behaviour lives.
- "Not found in code" is written where something one might expect does not exist.

## Contents

- Part A, High-Level Design (HLD)
  - A1 System context
  - A2 Runtime processes (containers)
  - A3 Deployment view
  - A4 Backend layers and module map
  - A5 Architectural principles as implemented
  - A6 End-to-end flows (overview)
  - A7 Cross-cutting concerns
  - A8 Capacity, state and limits
- Part B, Low-Level Design (LLD)
  - B1 Database
  - B2 Domain layer
  - B3 Service layer
  - B4 AI agent layer
  - B5 Conversation layer
  - B6 Telegram adapter and background jobs
  - B7 Reminder and outbox algorithms
  - B8 Staff API
  - B9 Staff authentication, sessions and CSRF
  - B10 Staff dashboard (Next.js)
  - B11 Configuration
  - B12 Observability
  - B13 Build, run, CI and database operations
  - B14 Test architecture
  - B15 Catalogues: result codes, audit actions, log events, callback data, constants
  - B16 Known limitations of the current implementation

# Part A: High-Level Design

## A1 System context

The system lets patients of one clinic book, reschedule and cancel appointments by chatting with a Telegram
bot, gives them reminders, and gives clinic staff a web dashboard to run the day and administer the clinic.

```mermaid
flowchart LR
    P([Patient<br/>Telegram app]) <-->|messages, buttons, contact| TG[Telegram Bot API]
    TG <-->|long polling getUpdates,<br/>sendMessage| BOT[Bot process<br/>clinic-bot]
    BOT <-->|generateContent with<br/>function calling| GEM[Google Gemini API]
    BOT <-->|SQL over TLS| DB[(PostgreSQL 17<br/>Supabase)]
    S([Receptionist / Clinic admin<br/>web browser]) <-->|HTTPS pages + /api/v1| WEB[Next.js dashboard<br/>web]
    WEB <-->|HTTP on 127.0.0.1| API[Staff API<br/>clinic-api]
    API <-->|SQL over TLS| DB
    GH[GitHub Actions CI] -.->|tests against<br/>postgres:17 container| GH
```

| External party | Interaction | Implemented in |
|---|---|---|
| Patient | Telegram private chat: text, the "Share phone number" contact button, inline buttons | `clinic/bot`, `clinic/conversation` |
| Receptionist, clinic admin | Browser; username and password; role `receptionist` or `admin` | `apps/web`, `clinic/api` |
| Telegram Bot API | Long polling for `message` and `callback_query` updates; `sendMessage`, chat actions, editing reply markup | `clinic/bot/telegram_app.py` |
| Google Gemini API | `generate_content` with up to 8 function declarations; model from `GEMINI_MODEL` | `clinic/agent/llm.py` |
| Supabase PostgreSQL | Session pooler, port 5432, TLS; roles `clinic_app` / `clinic_test_app` / `clinic_migrator` | `clinic/db`, `apps/backend/migrations` |

What the system deliberately does **not** do: give medical advice, store symptoms or health data, take
payments, serve group chats, or let the language model write data on its own.

## A2 Runtime processes (containers)

```mermaid
flowchart TB
    subgraph Laptop[Windows PC, started by scripts/start.ps1]
        WEB[web: Next.js server<br/>port WebPort, default 3000]
        API[api: FastAPI + uvicorn<br/>127.0.0.1:API_PORT, default 8000]
        BOT[bot: python-telegram-bot<br/>long polling, no inbound port]
        subgraph BOTIN[inside the bot process]
            CONV[ConversationService]
            AG[AgentLoop + 8 tools]
            JOBS[JobQueue: reminders 300 s,<br/>outbox 60 s]
        end
    end
    WEB -->|rewrite /api/v1/* to 127.0.0.1:API_PORT| API
    API --> DB[(PostgreSQL schema clinic)]
    BOT --> DB
    API -.->|writes notifications rows<br/>in the same transaction| DB
    JOBS -.->|drains notifications,<br/>sends reminders| DB
```

| Process | Technology | Responsibility | Inbound | Outbound |
|---|---|---|---|---|
| `bot` (`uv run clinic-bot`) | Python 3.14, python-telegram-bot 22.8 with JobQueue (APScheduler), google-genai, SQLAlchemy async + asyncpg | All patient conversations, the AI agent, reminders, delivery of clinic notices | none (long polling) | Telegram, Gemini, PostgreSQL |
| `api` (`uv run clinic-api`) | FastAPI 0.162, uvicorn 0.54 | Staff API: authentication, daily work, administration | HTTP on 127.0.0.1 only | PostgreSQL |
| `web` (`next start`) | Next.js 16 (React 19), TanStack Query, shadcn/ui | Staff dashboard pages; forwards `/api/v1/*` to the API so the browser talks to one origin | HTTP on `WebPort` | the API on loopback |
| database | PostgreSQL 17 (Supabase) | Single source of truth for every slot, booking, reminder, notice, ticket, alert, account and audit row | pooler | n/a |

Key interaction rules:

- The API and the bot **never call each other**. The only channel from staff actions to patients is the
  `notifications` table (transactional outbox, B7.2), drained by the bot, which is the only holder of the
  Telegram token.
- Both Python processes use the **same service classes** (`clinic/services`) and therefore the same booking
  rules; the dashboard adds no business rules of its own.
- State that lives only in the bot's memory: conversation history, pending confirmations, registration
  progress, rate-limit counters, session greetings, per-user locks (A8).

## A3 Deployment view

- **Development / demo:** one Windows PC runs the three processes through `scripts/start.ps1` (B13.1); logs
  and PIDs go to `logs/`. The database is a hosted Supabase project (region `eu-west-3`, reached through the
  session pooler, decision D-23) with two schemas: `clinic` (demo data, synthetic) and `clinic_test` (tests).
- **CI:** GitHub Actions on every push and pull request; the backend job uses a throwaway `postgres:17`
  container and placeholder secrets (B13.3).
- **Not implemented** (documented only): a cloud deployment, Telegram webhook mode, containers. The Docker
  Compose route was replaced by the PowerShell scripts (D-31).

## A4 Backend layers and module map

```mermaid
flowchart TB
    subgraph Entry[Entry points]
        BOTM[bot/__main__ + telegram_app]
        APIM[api/__main__ + app + routes_*]
    end
    RT[runtime.py<br/>composition root for the bot]
    CONV[conversation/<br/>service, registration, appointment_actions]
    AGENT[agent/<br/>llm, loop, tools, prompt, pending,<br/>grounding, guardrails, rate_limit, memory]
    SVC[services/<br/>booking, availability, patients, staff_ops,<br/>admin, staff_auth, reminders, notifications, ...]
    DOM[domain/<br/>slots, dates, appointments, patients,<br/>messages, results]
    DBL[db/<br/>models, session]
    CFG[config.py]
    OBS[observability.py]
    BOTM --> RT --> CONV --> AGENT --> SVC
    CONV --> SVC
    APIM --> SVC
    APIM -.->|RateLimiter class only| AGENT
    SVC --> DBL --> CFG
    SVC --> DOM
    AGENT --> DOM
    CONV --> DOM
```

Verified import directions (`grep` of `from clinic.<package>` per package):

| Package | Imports from |
|---|---|
| `domain` | nothing in the project |
| `services` | `db`, `domain`, `observability` |
| `agent` | `domain`, `services`, `observability` |
| `conversation` | `agent`, `domain`, `services`, `observability` |
| `bot` | `config`, `conversation`, `domain`, `observability`, `runtime`, `services` |
| `api` | `agent` (only `RateLimiter`), `config`, `db`, `domain`, `observability`, `services` |
| `db` | `config` |

Two pragmatic shortcuts exist: the API reuses the agent's in-memory `RateLimiter` class for login throttling,
and `GET /api/v1/doctors` queries the `Doctor` model directly in the route (`api/routes_staff.py:107-116`)
instead of through a service.

## A5 Architectural principles as implemented

1. **The database is the source of truth; the model is not.** Slots are computed from schedules, leave and
   bookings at request time; the model never decides availability (B3.2, B3.3).
2. **Safety by construction, not by prompt.** Emergency detection runs before the model (B4.7); the model
   cannot write (write tools only stage, B4.3); the patient confirms with a single-use button (B4.5, B5.5);
   identity comes from the session (`ToolContext`), never from model output; replies with a time or fee that
   no tool returned are blocked (B4.6); patient names and phone numbers are never sent to the model (D-16).
3. **Defence in depth for double booking:** service check, patient row lock, partial unique index and
   exclusion constraint (B1.3, B3.3).
4. **One rule set, two front ends:** bot and staff API share the service layer.
5. **Reliable side effects:** reminders are claimed by a unique key (at most once); clinic notices go through a
   transactional outbox (at least once) (B7).
6. **Everything auditable:** every tool call and every write is in an append-only audit log with no free text
   (B1.3, B3.9).
7. **Privacy by default:** consent before storing anything; no chat text in the database or logs; deletion
   anonymises (B3.4, B12).

## A6 End-to-end flows (overview)

### A6.1 Patient books through the agent

```mermaid
sequenceDiagram
    participant P as Patient
    participant B as Bot adapter
    participant C as ConversationService
    participant A as AgentLoop
    participant G as Gemini
    participant S as Services
    participant D as PostgreSQL
    P->>B: "GP tomorrow morning"
    B->>C: handle_text (per-user lock, typing...)
    C->>C: emergency check, rate limit, length, patient lookup
    C->>A: run(ToolContext from session)
    A->>G: prompt + history + message
    G-->>A: call list_doctors, check_availability
    A->>S: tools (validated, audited)
    S->>D: queries
    A->>G: tool results
    G-->>A: call book_appointment(slot_start)
    A->>S: precheck only, then stage pending book
    G-->>A: reply text (grounding checked)
    C-->>P: reply + code-rendered summary [Confirm][Change]
    P->>B: tap Confirm (v1:confirm:token)
    B->>C: handle_callback
    C->>S: BookingService.book (lock, re-check, insert)
    S->>D: one transaction + audit
    C-->>P: "Booked! Your reference is APT-..."
```

### A6.2 Staff cancels; the patient is notified

Dashboard `POST /api/v1/appointments/{id}/cancel` (cookie + CSRF) → `StaffOpsService.cancel` writes the
cancellation, the outbox row and the audit row in one transaction → within about 60 s the bot's outbox job
sends "Sorry, the clinic has cancelled your appointment ... Reason: ..." with a **Reschedule** button; after
3 failed attempts the appointment is flagged on the dashboard (B7.2).

### A6.3 Reminders

Every 5 minutes the bot claims and sends due reminders: 24 hours before (with Confirm, Reschedule and Cancel
buttons) and 2 hours before (no buttons), each at most once; failed deliveries flag the appointment for staff
(B7.1).

## A7 Cross-cutting concerns

| Concern | Implementation |
|---|---|
| Authentication (staff) | argon2id passwords, server-side sessions (token hash only), HttpOnly SameSite=Lax cookie, 60-min idle and 12-h absolute limits, lockout 5/15 min for real and unknown usernames, per-client login limit (B9) |
| Authorisation | API dependencies `Staff` and `Admin` on every route; role check is server-side (B8.3); database roles restricted to one schema with DML only (B1.1) |
| Patient identity | Telegram user id from the update; phone only via Telegram's own-contact sharing; `ToolContext.patient_id` from the database (B5) |
| CSRF | HMAC of the session token in `X-CSRF-Token` on every state-changing request (B9) |
| Input validation | Pydantic models with `extra="forbid"` on every API body and tool argument; domain validators for names and phones; database CHECK constraints as the last line (B1.3, B8.4) |
| Prompt injection | tool results declared as data; no identity in tool arguments; write tools stage only; grounding guard; FAQ answers only from approved rows (B4) |
| Privacy | consent first; no health data columns; conversation in memory only (2 h); redacted logs; deletion anonymises (B3.4, B12) |
| Errors | patient-facing fallbacks always include the clinic phone (B5.1); one API error envelope with request id and no internals (B8.2) |
| Observability | JSON logs with request ids, health and readiness endpoints, scheduler heartbeat, audit trail (B12) |
| Time | stored in UTC; converted with the clinic's IANA zone from `clinic_settings` for slots, dates and display (B2.5) |
| Configuration | `.env` for infrastructure and secrets (B11); clinic behaviour in `clinic_settings`, editable by the admin |

## A8 Capacity, state and limits as built

- **Single bot process.** Conversation memory, pending confirmations, registration progress, rate limits,
  greetings and per-user locks are in process memory, so the bot cannot run as several instances without
  moving that state to a shared store; a restart forgets in-flight conversations and pending buttons (a stale
  button answers "This request has expired"). The staff API holds no conversation state; only its login rate
  limiter is in memory.
- **Concurrency:** the bot processes updates concurrently across users and serially per user; each Python
  process has a database pool of 5 + 5 connections.
- **Model limits:** at most 5 tool calls and 25 s per reply, 8 s per model call; the free Gemini tier has daily
  request quotas (operational constraint, not code).
- **Settings propagation:** up to 30 s per process (cache TTL).
- **Measured reply time:** the final evaluation (`docs/testing/eval-2026-11-05-production-final.md`) recorded a
  p95 of 20.34 s on the free model tier with the database in another region; the 5-second target (NFR-01) is
  not met.

# Part B: Low-Level Design

## B1 Database

PostgreSQL 17 on Supabase (development) and a `postgres:17` container (CI). The schema is created only by
Alembic migrations (`apps/backend/migrations/versions/0001..0003`); the ORM models (`clinic/db/models.py`)
mirror it and an integration test (`test_schema.py::test_models_match_the_migrated_schema`) fails if they
drift.

### B1.1 Roles, schemas and privileges

One-time bootstrap `infrastructure/db/bootstrap.sql`, run as the project owner (idempotent; reverse with
`bootstrap_rollback.sql`, which is destructive):

| Object | Definition |
|---|---|
| Extension | `btree_gist` in schema `extensions` (needed by the exclusion constraint) |
| Roles | `clinic_migrator`, `clinic_app`, `clinic_test_app`, each `LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS NOINHERIT`; passwords are set separately (`scripts/db_role_passwords.py` prints SCRAM-SHA-256 verifiers, so plaintext never leaves `.env`) |
| Schemas | `clinic` (development/demo data) and `clinic_test` (tests); `revoke all ... from public` |
| Schema grants | `clinic_migrator`: USAGE + CREATE on both; `clinic_app`: USAGE on `clinic` only; `clinic_test_app`: USAGE on `clinic_test` only |
| Role settings | `statement_timeout = 10s` and `idle_in_transaction_session_timeout = 30s` for both app roles |

Migration `0001` adds, per target schema: default privileges so tables created by `clinic_migrator` grant
`SELECT, INSERT, UPDATE, DELETE` (tables) and `USAGE, SELECT` (sequences) to that schema's app role;
`REVOKE UPDATE, DELETE ON audit_log` from the app role; and on every table `ENABLE ROW LEVEL SECURITY` with a
policy `app_access FOR ALL TO <app role> USING (true) WITH CHECK (true)` (`0001_baseline.py:353-374`). The
net effect: the app role can read and write rows only in its own schema, cannot create or alter objects,
cannot change or delete audit rows, and the test role cannot even see the development schema.

Migrations select their target with `-x schema=clinic|clinic_test` (only those two configured schemas are
accepted), set `search_path` to that schema only, keep `alembic_version` inside it, and refuse offline SQL
generation (`migrations/env.py`).

### B1.2 Entity-relationship model (15 tables)

```mermaid
erDiagram
    staff_users ||--o{ staff_sessions : "has (ON DELETE CASCADE)"
    doctors ||--o{ doctor_schedules : "weekly blocks"
    doctors ||--o{ doctor_leaves : "leave days"
    doctors ||--o{ appointments : "sees"
    patients ||--o{ appointments : "books"
    appointments |o--o{ appointments : "rescheduled_from"
    appointments ||--o{ reminders : "24h, 2h"
    appointments ||--o{ notifications : "clinic notices"
    patients ||--o{ notifications : "recipient"
    patients ||--o{ handoff_tickets : "asks for staff"
    patients |o--o{ emergency_alerts : "sender, if registered"
    staff_users |o--o{ appointments : "created_by / attendance_marked_by"
    staff_users |o--o{ doctor_leaves : "created_by"
    staff_users |o--o{ handoff_tickets : "resolved_by"
    staff_users |o--o{ emergency_alerts : "acknowledged_by"
    staff_users |o--o{ clinic_info : "updated_by"
    staff_users |o--o{ clinic_settings : "updated_by"
```

`audit_log` (`patient_id` deliberately has **no** foreign key, so audit history survives anything) and
`login_failures` stand alone. Every foreign key to `doctors`, `patients` and `appointments` is
`ON DELETE RESTRICT`; references to `staff_users` have no `ON DELETE` clause (default `NO ACTION`); only
`staff_sessions` cascades. Primary keys are UUIDs (`gen_random_uuid()` in the database; the ORM generates
UUIDv7 client-side), except `clinic_settings` (smallint, always 1), `audit_log` (bigint identity) and
`login_failures` (hash).

### B1.3 Tables, columns and constraints

All timestamps are `timestamptz` and stored in UTC. Constraint names follow the naming convention in
`models.py:36-42` (`pk_`, `uq_`, `fk_`, `ck_`, `ix_`).

**`staff_users`**: `id`, `username`, `display_name`, `password_hash` (argon2id), `role`, `active` (default
true), `failed_attempts` (default 0), `first_failed_at`, `locked_until`, `last_login_at`, `created_at`,
`updated_at`. Checks: `role IN ('receptionist','admin')`, `char_length(username) BETWEEN 3 AND 40`,
`failed_attempts >= 0`. Unique index `ux_staff_users_username_lower ON (lower(username))`.

**`staff_sessions`**: `id`, `staff_user_id` (FK, cascade), `token_hash bytea` (unique; SHA-256 of the token),
`created_at`, `expires_at`, `last_seen_at`, `revoked_at`. Index on `staff_user_id`.

**`clinic_settings`** (single row): `id smallint` with check `id = 1`; `clinic_name`, `phone`, `address`,
`staff_hours_text`, `timezone`, `emergency_number` (all text not null); `emergency_phrases text[]` (default
empty); `cutoff_minutes` (default 120, check 0-10080); `booking_window_days` (default 30, check 1-365);
`max_upcoming_per_patient` (default 3) and `max_per_doctor_per_day` (default 1), both check ≥ 1;
`morning_end` (default 12:00) and `afternoon_end` (default 17:00) with check `afternoon_end > morning_end`;
`updated_by`, `updated_at`.

**`doctors`**: `id`, `name` and `specialty` (check length 2-80), `active` (default true), timestamps. Index
on `active`.

**`doctor_schedules`**: `id`, `doctor_id`, `weekday smallint` (check 0-6), `start_time`, `end_time` (check
`end_time > start_time`), `slot_minutes smallint` (default 15, check 5-120), timestamps. Index
`(doctor_id, weekday)`. Several rows per weekday model breaks; overlaps between rows are prevented by the
service (B3.11), not by the database.

**`doctor_leaves`**: `id`, `doctor_id`, `leave_date date`, `reason` (default `''`, check ≤ 200 characters),
`created_by`, `created_at`. Unique `(doctor_id, leave_date)`.

**`patients`**: `id`, `telegram_user_id bigint` (unique, nullable), `phone` (unique, nullable), `full_name`,
`consent_at`, `consent_source`, `registered_via`, timestamps, `deleted_at`. Checks:

- `ck_patients_identity`: `deleted_at IS NOT NULL OR (phone, full_name and consent_at all NOT NULL)`, so an
  active patient always has consent;
- `ck_patients_full_name`: null, or 2-60 characters with no digit;
- `ck_patients_phone`: null, or E.164 `^\+[1-9][0-9]{6,14}$`;
- `consent_source IN ('telegram','staff_verbal')`; `registered_via IN ('bot','staff')`;
- `ck_patients_deleted_anonymised` (migration 0002): `deleted_at IS NULL OR (phone IS NULL AND
  telegram_user_id IS NULL)`, so a deleted record can never be matched again or block a new registration.

There are **no** columns for symptoms or any health information (a test asserts the exact column set).

**`appointments`**: `id`; `ref text` unique, default `format_appointment_ref(nextval('appointment_ref_seq'))`
which gives `APT-` followed by the number zero-padded to at least 6 digits (`APT-000001`, `APT-1234567`);
`patient_id`, `doctor_id`; `start_time`, `end_time` (check end > start); `status` (default `booked`, check one
of `booked, cancelled, completed, no_show`); `source` (`bot` or `staff`); `rescheduled_from` (self FK);
`cancelled_at`, `cancelled_by_kind` (`patient, staff, system`), `cancel_reason` (≤ 200); check
`ck_appointments_cancellation`: a cancelled row must have `cancelled_at` and `cancelled_by_kind`;
`patient_confirmed_at`; `staff_attention_reason`, `staff_attention_at`; `created_by_staff_id`;
`attendance_marked_by`, `attendance_marked_at`; timestamps.

**Double-booking defences on `appointments`** (`0001_baseline.py:220-227`):

```sql
CONSTRAINT ex_appt_no_overlap EXCLUDE USING gist (
    doctor_id WITH =, tstzrange(start_time, end_time) WITH &&
) WHERE (status = 'booked')

CREATE UNIQUE INDEX ux_appt_doctor_start_booked ON appointments (doctor_id, start_time)
    WHERE status = 'booked';
```

The unique index stops two bookings of the same start; the exclusion constraint stops any two **overlapping**
booked intervals for one doctor (for example after an admin changes slot length). Cancelled rows are ignored
by both, so a cancelled slot can be booked again. Other indexes: `(patient_id, status, start_time)`, partial
`(start_time) WHERE status='booked'` (reminder scan), `(doctor_id, start_time)`.

**`reminders`**: `id`, `appointment_id`, `type` (`24h` or `2h`), `status` (`pending, sent, failed,
skipped`, default `pending`), `attempts`, `last_error`, `claimed_at`, `sent_at`, `created_at`. **Unique
`(appointment_id, type)`**: the claim mechanism of B7.1.

**`notifications`** (outbox): `id`, `appointment_id`, `patient_id`, `kind` (`clinic_cancelled` or
`doctor_leave`), `reason`, `status` (`pending, sent, failed`), `attempts`, `next_attempt_at` (default now),
`last_error`, `created_at`, `sent_at`. Unique `(appointment_id, kind)`; partial index `(next_attempt_at)
WHERE status = 'pending'`.

**`handoff_tickets`**: `id`, `patient_id`, `reason` (one of the five `TicketReason` values), `status` (`open`
or `resolved`), `created_at`, `resolved_by`, `resolved_at`; check `status = 'open' OR resolved_at IS NOT
NULL`; **partial unique index `ux_handoff_tickets_open_per_patient (patient_id) WHERE status = 'open'`**
(one open ticket per patient).

**`emergency_alerts`**: `id`, `patient_id` (nullable: unregistered senders), `telegram_user_id`, `created_at`,
`acknowledged_by`, `acknowledged_at`; check that at least one sender id is present; partial index
`(created_at) WHERE acknowledged_at IS NULL`. No message text is stored.

**`clinic_info`** (FAQ): `id`, `topic` (unique, check `^[a-z0-9_]{1,40}$`), `aliases text[]`, `answer` (1-2000
characters), `updated_by`, timestamps.

**`audit_log`**: `id bigint GENERATED ALWAYS AS IDENTITY`, `ts` (default now), `actor_type` (`agent, staff,
system, patient_button`), `actor_id`, `patient_id` (no FK), `action`, `args_json jsonb` (default `{}`),
`result`, `latency_ms`, `request_id`. Indexes `(ts DESC)` and `(patient_id, ts DESC)`. **Append-only**:
trigger `audit_log_append_only BEFORE UPDATE OR DELETE ... FOR EACH ROW EXECUTE FUNCTION reject_audit_change()`
raises `audit_log is append-only` (this blocks even the table owner), in addition to the revoked privileges.

**`login_failures`** (migration 0003): `username_hash bytea` primary key (HMAC-SHA256 of the lower-cased
username with `AUTH_SECRET`), `failed_attempts`, `first_failed_at`, `locked_until`, `updated_at` (indexed for
the purge). RLS enabled like the other tables.

### B1.4 Migrations

| Revision | Upgrade | Downgrade |
|---|---|---|
| `0001_baseline` | default privileges, sequence `appointment_ref_seq`, function `format_appointment_ref`, 14 tables with constraints and indexes, audit trigger function and trigger, audit revoke, RLS + policy on every table | drops the 14 tables in reverse order, both functions and the sequence, and revokes the default privileges |
| `0002_patients_deleted_anonymised` | adds `ck_patients_deleted_anonymised` | drops it |
| `0003_login_failures` | creates `login_failures` with RLS and policy | drops it |

`test_migrations.py` runs `downgrade base` and `upgrade head` twice and compares the table list, so every
migration is proven reversible.

### B1.5 Connections (`clinic/db/session.py`, `clinic/config.py`)

- Driver `postgresql+asyncpg`, through the Supabase **session pooler** on port 5432 (the direct host is
  IPv6-only); the user name is `<role>.<SUPABASE_PROJECT_REF>`, or the bare role on plain PostgreSQL (CI).
- `DbTarget`: `app` = `clinic_app` on `DB_SCHEMA`; `test` = `clinic_test_app` on `DB_TEST_SCHEMA`; `migrator`
  = `clinic_migrator` on one of the two. The models carry no schema name; the engine maps them with
  `schema_translate_map = {None: <schema>}`.
- Engine: `pool_pre_ping=True`, `hide_parameters=True` (bound values such as phone numbers never reach logs),
  `pool_size=5`, `max_overflow=5`, `pool_recycle=1800`, `pool_timeout=10`; `NullPool` for Alembic, the seed,
  `create_admin` and the E2E fixtures. Driver arguments: connect timeout 10 s, `command_timeout` 15 s (longer
  than the role's 10 s `statement_timeout`, so PostgreSQL cancels first), `application_name =
  clinic-<role>`. Sessions use `expire_on_commit=False`.
- TLS (`database_ssl`): with `DB_SSL_ROOT_CERT`, an SSL context with that CA, hostname check and TLS ≥ 1.2
  (verify-full); without it, `require` (encrypted, not verified) and a `db_tls_unverified` warning;
  `ENV=production` refuses to start without the CA or with `DB_SSL=disable`. `DB_SSL=disable` exists for the CI
  container.

## B2 Domain layer (`clinic/domain`)

Pure Python: no database, no network, no clock (time is always passed in). Every other layer depends on it;
it depends on nothing in the project.

### B2.1 `results.py`: result codes

`ResultCode` (a `StrEnum`) is shared by tools, services and the staff API error envelope:
`OK, NO_MATCH, NO_SLOTS, INVALID_DATE, AMBIGUOUS_DATE, DOCTOR_NOT_WORKING, NOT_FOUND, PENDING_CONFIRMATION,
SLOT_UNAVAILABLE, SLOT_TAKEN, LIMIT_REACHED, WITHIN_CUTOFF, ALREADY_CANCELLED, NONE, CREATED, ALREADY_OPEN,
INVALID_ARGS, ERROR, VALIDATION_ERROR, FORBIDDEN, UNAUTHENTICATED, ACCOUNT_LOCKED, RATE_LIMITED`
(`clinic/domain/results.py:6-29`).

### B2.2 `appointments.py`: status state machine and cut-off

`AppointmentStatus`: `booked`, `cancelled`, `completed`, `no_show`. Allowed transitions and who may make them
(`clinic/domain/appointments.py:17-26`):

| From | To | Allowed actors |
|---|---|---|
| booked | cancelled | patient, staff, admin, system |
| booked | completed | staff, admin |
| booked | no_show | staff, admin |
| completed | no_show | admin only (correction of a mis-click) |
| no_show | completed | admin only |

Every other transition is refused (`can_transition` returns `False`). `cancelled` is terminal.

```mermaid
stateDiagram-v2
    [*] --> booked: bot Confirm or staff booking
    booked --> cancelled: patient, staff, admin, system
    booked --> completed: staff/admin, only after start
    booked --> no_show: staff/admin, only after start
    completed --> no_show: admin only
    no_show --> completed: admin only
    cancelled --> [*]
```

`within_cutoff(start, now, cutoff_minutes)` is `start - now < cutoff_minutes`, so it is also true once the
appointment has started (`appointments.py:33-35`). The "only after start" rule for attendance is enforced in
`StaffOpsService.mark_attendance` (B3.10), not in the state table.

### B2.3 `messages.py`: transport-neutral messages

- `IncomingUser(telegram_user_id)`.
- `Button(text, callback_data=None, request_contact=False)`. Its constructor refuses `callback_data` longer
  than 64 bytes, Telegram's limit (`messages.py:16-23`).
- `Reply(text, inline_buttons=(), contact_button=None, remove_keyboard=False)`.
- `callback(kind, value)` returns `"v1:{kind}:{value}"`; the `v1` prefix versions the button protocol.
- `plain_text(text)` removes paired `**...**` and `__...__` markers from model text (regex
  `(\*\*|__)(.+?)\1`), because replies are sent as plain text (`messages.py:38-43`, decision D-53).

### B2.4 `patients.py`: name and phone rules

- `normalise_name(raw)`: rejects control characters; collapses whitespace; length 2 to 60; no digits; at least
  one letter; every character must be a letter, a combining mark, a space, `-`, `'`, `.` or `’`
  (`patients.py:20-33`). Raises `InvalidNameError`.
- `first_name(full_name)`: text before the first space.
- `normalise_phone(raw, default_region=None)`: only `0-9 + - ( )` and spaces are allowed. Without a leading
  `+` and without a default region a `+` is prepended (Telegram contacts arrive as international digits
  without the plus). Parsed and validated with `phonenumbers`; returns E.164. Raises `InvalidPhoneError`
  (`patients.py:40-53`). Staff screens pass region `IN` (`staff_ops.py:35`).

### B2.5 `slots.py`: slot arithmetic

- Types: `ScheduleBlock(weekday 0=Monday, start, end, slot_minutes)`, `Slot(start, end)` (aware datetimes in the
  clinic time zone), `DateWindow(first, last)` with `contains`, `PartOfDay` = morning, afternoon, evening.
- `booking_window(now, tz, days)`: today through today + `days`, both inclusive, in the clinic time zone.
- `day_slots(blocks, day, tz)`: for each block of that weekday, sorted by start, step through the block in
  `slot_minutes`; a partial slot at the end of a block is dropped (`slots.py:51-61`).
- `overlaps(slot, busy)`: half-open interval overlap.
- `free_slots(...)`: empty when the day is outside the window or a leave day; otherwise the day's slots whose
  start is after `now` and that overlap no booked interval (`slots.py:68-81`).
- `part_of_day(clock, morning_end, afternoon_end)`: before `morning_end` = morning, before `afternoon_end` =
  afternoon, otherwise evening.
- Formatting: `format_time_12h` gives "9:30 AM"; `format_date_long` gives "Monday, 7 January 2030" with fixed
  English names (not the process locale).

### B2.6 `dates.py`: deterministic date phrases

The model passes the patient's phrase unchanged; code decides the date (`dates.py:1-11`). `resolve_date(phrase,
today)` lower-cases, trims trailing `.!?`, drops a leading "the ", and returns `Resolved(day)`,
`Ambiguous(reason)` or `Unrecognised()`:

| Phrase | Result |
|---|---|
| `today`, `tomorrow`, `day after tomorrow` | today + 0, 1, 2 |
| `<weekday>` or `this <weekday>` | nearest occurrence on or after today |
| `next <weekday>` | same as above, but today's weekday moves 7 days ahead |
| `YYYY-MM-DD` | that date |
| `D Month [YYYY]`, `D of Month`, `Month D [YYYY]` (ordinals and 3-letter months, `sept`) | that date; without a year, a date already past this year means next year |
| bare day (`the 5th`) | this month if not yet past, else next month; **ambiguous** in the last 7 days of a month |
| numeric forms such as `13/01/2030` | unrecognised (D/M and M/D orders are both in use) |

## B3 Service layer (`clinic/services`)

Services own all business rules and all database access. Each one receives an
`async_sessionmaker[AsyncSession]` and, where needed, a `clock` callable (default `datetime.now(UTC)`) so
tests can pin time. The bot and the staff API use **the same service classes**; nothing about booking rules
is duplicated in the API or the dashboard.

Transaction pattern used everywhere: `async with session_factory() as session, session.begin():` so one
`async with` block is one database transaction, committed on normal exit and rolled back on any exception.
Audit rows are added to the same session, so they commit or roll back with the change they describe
(`clinic/services/audit.py:47`).

### B3.1 `ClinicSettingsService` (`clinic_settings.py`)

Reads row `id = 1` of `clinic_settings` into an immutable `ClinicSettingsView` (name, phone, address,
`staff_hours_text`, `tz: ZoneInfo`, emergency number and phrases, cut-off minutes, booking-window days, the
two booking limits, `morning_end`, `afternoon_end`). The view is cached for **30 seconds** per process
(time-based invalidation only, `clinic_settings.py:36-53`), so an admin's edit reaches the bot and the API
within 30 s. A missing row raises `ClinicSettingsMissingError`.

### B3.2 `AvailabilityService` (`availability.py`)

`load_calendar(session, doctor_id, window, tz)` makes **three queries** and returns a `DoctorCalendar`, or
`None` when the doctor does not exist or is inactive:

1. the doctor's `doctor_schedules` rows (all weekdays);
2. `doctor_leaves.leave_date` inside the window;
3. `(start_time, end_time)` of the doctor's `booked` appointments overlapping the window.

`DoctorCalendar` methods: `works_on(day)`, `grid_on` (bookable slots ignoring bookings), `free_on`,
`is_taken(slot)`, `next_days_with_slots(after, ..., count)` (scans day by day to the end of the window).

`AvailabilityService.day(doctor_id, day, part=None)` returns a `DayAvailability`:

| Code | When | Extra data |
|---|---|---|
| `NOT_FOUND` | doctor missing or inactive | |
| `INVALID_DATE` | day outside the booking window | doctor name |
| `DOCTOR_NOT_WORKING` | no schedule block on that weekday | the next day that has free slots |
| `OK` | free slots exist (filtered by part of day if given) | the slots |
| `NO_SLOTS` | nothing free (in that part of day) | next 3 days with free slots; other parts of the day that do have slots |

### B3.3 `BookingService` (`booking.py`)

The heart of the system. Constants: `DOUBLE_BOOKING_CONSTRAINTS = {"ux_appt_doctor_start_booked",
"ex_appt_no_overlap"}`, `ALTERNATIVES = 3` (`booking.py:31-32`).

**`_check(session, view, now, patient_id, doctor_id, slot_start, exclude_appointment_id)`**
(`booking.py:145-195`), shared by the read-only pre-check and the write:

1. Load the doctor's calendar; inactive or missing doctor: `NOT_FOUND`.
2. The requested start must be **exactly** one of the grid slots for that day (schedule, leave, window and
   "start after now" applied): otherwise `SLOT_UNAVAILABLE`.
3. The slot overlaps a booked appointment: `SLOT_TAKEN`.
4. Count the patient's booked appointments starting after now (excluding the appointment being moved, for a
   reschedule): at or above `max_upcoming_per_patient`: `LIMIT_REACHED` with reason `max_upcoming`.
5. Count the patient's booked appointments with the same doctor on that clinic day: at or above
   `max_per_doctor_per_day`: `LIMIT_REACHED` with reason `same_doctor_same_day`.
6. Otherwise `OK` with the slot.

**`precheck(...)`**: runs `_check` in a read-only session. Used when the agent stages a booking or
reschedule, and when a patient picks an alternative slot.

**`book(patient_id, doctor_id, slot_start, source, actor_type="patient_button", staff_user_id=None)`**
(`booking.py:197-253`), in one transaction:

1. `SELECT patient ... WHERE id = ? AND deleted_at IS NULL FOR UPDATE`: the patient row lock serialises one
   patient's parallel taps, so the limits cannot be exceeded by racing requests. Missing: `NOT_FOUND`.
2. `_check` again inside the transaction (never trust the earlier pre-check).
3. Not OK and not `SLOT_TAKEN`: audit `appointment.book` with that code and return it.
4. OK: insert the appointment (`status='booked'`, `source`, `created_by_staff_id`) and `flush()`. The database
   partial unique index and exclusion constraint fire here if another patient won the race.
5. Audit `appointment.book` = OK, commit, return the reference (`APT-000123`) and id.
6. On `IntegrityError` whose constraint name is one of the two double-booking constraints, or when step 3 saw
   `SLOT_TAKEN`: `_slot_taken` audits `SLOT_TAKEN` in a new transaction and returns up to **3 nearest free
   slots** for the same doctor (`nearest_free_slots`: same day first, then following days until three later
   slots exist; sorted by distance from the requested time, ties earlier first; returned in time order). Any
   other `IntegrityError` is re-raised.

The constraint name is read from the driver exception (`exc.orig.__cause__.constraint_name`,
`booking.py:102-105`).

**Managing existing appointments**

| Method | Behaviour |
|---|---|
| `upcoming_for_patient(patient_id)` | the patient's booked appointments starting after now, soonest first, with doctor name |
| `check_change(patient_id, reference)` | looks up by reference **scoped to that patient** (another patient's reference is `NOT_FOUND`); then `_changeable` |
| `check_change_by_id(patient_id, appointment_id)` | same, by id (used by reminder and notice buttons, which could be forged) |
| `_changeable` | cancelled: `ALREADY_CANCELLED`; not booked, or within the cut-off (or started): `WITHIN_CUTOFF`; else `OK` |
| `confirm_presence(patient_id, appointment_id)` | row lock `FOR UPDATE OF appointments`; cancelled: `ALREADY_CANCELLED`; not booked or already started: `WITHIN_CUTOFF`; else sets `patient_confirmed_at`; audit `appointment.patient_confirm` |
| `cancel(patient_id, appointment_id)` | row lock; `_changeable`; if OK: `status='cancelled'`, `cancelled_at`, `cancelled_by_kind='patient'`; audit `appointment.cancel`; a repeat returns `ALREADY_CANCELLED` and changes nothing |
| `reschedule(patient_id, appointment_id, new_slot_start)` | one transaction: lock the patient row, lock the appointment, `_changeable`, `_check` for the new slot excluding the old appointment, cancel the old one (`cancel_reason='Rescheduled by the patient'`), flush, insert the new one with `rescheduled_from = old.id` and the old `source`, flush (constraints fire). If the new slot was taken, everything rolls back and the old booking is unchanged; alternatives are returned as for `book` |

Audit rows for these patient actions use `actor_type='patient_button'`.

### B3.4 `PatientService` (`patients.py`)

- `get_by_telegram(telegram_user_id)`: active (not deleted) patient or `None`.
- `check_phone(phone, telegram_user_id)` returns `AVAILABLE`, `WALK_IN_MATCH` (a staff-created record with no
  Telegram link), `ALREADY_YOURS` or `LINKED_ELSEWHERE`.
- `register_from_telegram(telegram_user_id, phone, full_name, consented_at)`: **nothing is stored before this
  call**. One transaction: if this Telegram user already has a patient: `ALREADY_REGISTERED`. Lock the patient
  with that phone (`FOR UPDATE`). Linked to another Telegram account: open (or reuse) a
  `registration_conflict` handoff ticket for the owner and return `LINKED_ELSEWHERE`. A walk-in with that
  phone: link it (set Telegram id, name, consent) and return `LINKED_WALK_IN`. Otherwise insert a new patient
  (`registered_via='bot'`, `consent_source='telegram'`): `REGISTERED`. Audit `patient.register`. On an
  `IntegrityError` (lost race on the phone or Telegram id unique constraint) the whole call is retried once.
- `flag_phone_conflict(phone)`: opens a `registration_conflict` ticket on the owner; audit
  `patient.phone_conflict`.
- `delete_patient(patient_id, now)`: one transaction: lock the patient, lock and cancel every booked
  appointment starting after now (`cancel_reason='Patient deleted their data'`), set
  `full_name='Deleted patient'`, `phone=NULL`, `telegram_user_id=NULL`, `deleted_at=now`; audit
  `patient.delete` with the number cancelled. Past appointments stay, linked to the anonymised row.

### B3.5 `DoctorService` (`doctors.py`)

`list_active(specialty=None)`: one query, active doctors ordered by name, with
`array_remove(array_agg(DISTINCT weekday), NULL)` from an outer join on schedules. The optional specialty
filter is a case-insensitive `ILIKE '%...%'` with `%`, `_` and `\` escaped (`doctors.py:20-40`).

### B3.6 `FaqService` (`faq.py`)

Reads all `clinic_info` rows on every question (admin edits apply at once). `find(topic)` normalises
(case-fold, `_` and `-` to spaces, collapse spaces) and returns the entry whose topic **or any alias** equals
the request exactly. No fuzzy matching. `topics()` lists all topics (given to the model on a miss).

### B3.7 Tickets and handoff (`tickets.py`, `handoff.py`)

- `TicketReason`: `patient_requested`, `agent_failed`, `registration_conflict`, `change_within_cutoff`,
  `other`.
- `TicketService.open_or_get(session, patient_id, reason)`: returns `ALREADY_OPEN` with the existing open
  ticket, otherwise inserts one inside a savepoint (`begin_nested`). If a concurrent request inserted first,
  the partial unique index (one open ticket per patient) raises `IntegrityError` and the method returns that
  ticket as `ALREADY_OPEN`.
- `HandoffService.request(patient_id, reason)`: `open_or_get` plus audit `handoff.request` (`actor_type
  'agent'`), returns `CREATED` or `ALREADY_OPEN`.

### B3.8 `AlertService` (`alerts.py`)

`raise_emergency(patient_id, telegram_user_id, now)`: at most **one alert per sender per 10 minutes**
(matched by Telegram id or patient id). Inserts an `emergency_alerts` row (no message text is stored) and
audits `emergency.alert` with `actor_type 'system'`. Returns whether a new alert was created.

### B3.9 `AuditService` (`audit.py`)

`AuditService.record(session, actor_type, actor_id, action, args, result, patient_id, latency_ms,
request_id=None)` adds an `audit_log` row to the caller's transaction. `actor_type` is one of `agent`,
`staff`, `system`, `patient_button`. **Guard:** any key named `text`, `message`, `name`, `phone` or
`full_name`, at any nesting depth, raises `ForbiddenAuditFieldError` (`audit.py:15-30`). The request id comes
from the argument or the current context variable.

### B3.10 `StaffOpsService` (`staff_ops.py`)

Receptionist operations behind the staff API. Errors are raised as `OperationRefusedError(code, message,
details)`, which the API turns into the error envelope.

- `appointment_rows(session, appointments, view, now)` loads patients, doctors and reminders for **any number
  of appointments in three queries** (no N+1) and builds `AppointmentOut`: id, reference, doctor, start, end,
  clinic-local `date` and `time_label`, status, source, patient (`id`, `full_name` or "Deleted patient",
  `phone`, `telegram` boolean), reminder statuses `{"24h", "2h"}`, `patient_confirmed`, `staff_attention`
  (reason and time), and `can_mark_attendance` (start passed and status booked/completed/no_show).
- `schedule(day)`: every active doctor (by name) with all of that clinic day's appointments in any status.
- `clinic_today()`: today's date and time-zone name in the clinic's zone (the dashboard never uses the PC
  clock, D-40).
- `attention()`: open tickets with patient; unacknowledged emergency alerts (with patient if known, else the
  raw Telegram id); appointments with a `staff_attention_reason`.
- `find_patients(phone)`: exact match on the normalised phone (region `IN`), never a listing.
- `book(principal, doctor_id, start, patient_id | new_patient)`: a walk-in first needs `verbal_consent=true`,
  a valid name and phone, and a phone not already on file (`CONFLICT`); it is created with
  `consent_source='staff_verbal'`, `registered_via='staff'` and audited `patient.create`. The booking then goes
  through `BookingService.book(source='staff', actor_type='staff')`, the same rules as the bot. A refusal
  becomes `SLOT_TAKEN`, `SLOT_UNAVAILABLE`, `LIMIT_REACHED` (with `details.reason`) or `NOT_FOUND`, with
  `details.alternatives` when available.
- `cancel(principal, appointment_id, reason)`: row lock; already cancelled: `ALREADY_CANCELLED`; only booked
  may be cancelled; **not bound by the bot's cut-off**. Sets `cancelled_by_kind='staff'` and the reason. If the
  patient is linked to Telegram and not deleted, inserts a `notifications` row (`kind='clinic_cancelled'`)
  **in the same transaction** (transactional outbox). Audit `appointment.staff_cancel`.
- `mark_attendance(principal, appointment_id, status)`: refused before the start time (`CONFLICT`); the state
  table decides; changing an existing completed/no-show mark needs admin (`FORBIDDEN`). Sets
  `attendance_marked_by/at`. Audit `appointment.attendance`.
- `clear_attention`, `resolve_ticket` (idempotent: an already resolved ticket is returned unchanged),
  `acknowledge_alert` (idempotent: the first acknowledgement is kept), each audited.
- `free_slots(doctor_id, day)`: `AvailabilityService.day` slots as `{start, time_label}`; an unknown doctor is
  `NOT_FOUND`; other non-OK codes give an empty list.

### B3.11 `AdminService` (`admin.py`)

- Doctors: create, update (`name`, `specialty`, `active`), audited `doctor.create` / `doctor.update`.
- Weekly schedule: `replace_schedule` validates blocks (weekday 0-6, end after start, slot 5-120 minutes, no
  overlapping blocks on one weekday), locks the doctor row (serialises concurrent edits), deletes the doctor's
  blocks and inserts the new set; audit `doctor.schedule`.
- Leave: `preview_leave(doctor_id, day)` lists booked appointments that day. `create_leave(..., reason,
  confirm_affected)` locks the doctor; if bookings exist and `confirm_affected` is false it refuses with
  `CONFLICT` and `details.affected` (the full appointment list); refuses a duplicate leave day; otherwise
  inserts the leave, cancels each affected booking (`cancelled_by_kind='staff'`, the reason) and adds a
  `notifications` row (`kind='doctor_leave'`) for each Telegram-linked patient, all in one transaction; audit
  `doctor.leave` with the count. `delete_leave` removes the day only; cancelled bookings are **not**
  restored.
- FAQ: paginated list; `save_faq` checks the topic is unique (and maps a racing `uq_clinic_info_topic`
  violation to the same `CONFLICT`); `delete_faq`. Audited `faq.save` / `faq.delete`.
- Settings: `update_settings` locks row 1, validates the time zone with `ZoneInfo` and `morning_end <
  afternoon_end`, writes only the fields sent; audit `settings.update` with field names.
- Audit viewer: filters `from`/`to` (whole clinic-time days, inclusive), `actor_type`, `action`,
  `patient_id`; newest first; paginated with a total count.
- Weekly metrics: appointments starting in the 7 days from `week_start` (clinic time): bookings by source
  (`bot`, `staff`), cancellations, and per doctor `completed`, `no_show`, `no_show_rate = no_show /
  (completed + no_show)` rounded to 4 places, 0 when the denominator is 0. Computed in Python from two
  queries.
- Staff users: list (paginated by username), create (`WeakPasswordError` / `InvalidUsernameError` become
  `VALIDATION_ERROR`; a taken username, detected by the `ux_staff_users_username_lower` index, becomes
  `CONFLICT` "That username is already taken."), update (`display_name`, `role`, `active`, `password`; an
  admin cannot deactivate or demote **their own** account; a new password revokes all of that user's open
  sessions), unlock (clears the lockout counters). Audited `staff_user.create/update/unlock`.

### B3.12 `StaffAuthService` (`staff_auth.py`)

Covered in B9.

### B3.13 `ReminderService` and `NotificationService`

Covered in B7.

## B4 AI agent layer (`clinic/agent`)

### B4.1 Provider boundary (`llm.py`)

- Provider-neutral transcript items: `UserText`, `ModelText(text, trusted=False)` (trusted = written by code),
  `ModelTurn(LlmTurn)`, `ToolResults([(ToolCall, ToolResult)])`. `LLM` is a `Protocol` with one method,
  `generate(system, transcript, tools) -> LlmTurn`.
- `GeminiLLM` (google-genai SDK):
  - `GenerateContentConfig(system_instruction, tools=[function declarations], automatic_function_calling
    disabled, temperature=0.2, max_output_tokens=1024)` (`llm.py:154-160`).
  - Each call is wrapped in `asyncio.timeout(LLM_TIMEOUT_SECONDS)`.
  - HTTP retry: `HttpRetryOptions(attempts=2, initial_delay=0.5, max_delay=1.0, jitter=0.25,
    http_status_codes=[500, 502, 503, 504])`, so one quick retry on server errors; 429 is deliberately not
    retried (on the free tier it means the daily quota is used up) (`llm.py:29-31`, D-50).
  - API errors, `httpx` errors, time-outs and `OSError` become `LlmUnavailableError` and log
    `llm_unavailable`; an empty response logs `llm_empty_response`.
  - Gemini 3 attaches "thought signatures" to function-call turns and rejects a follow-up that drops them, so
    model turns are replayed from the provider's raw `Content` (`llm.py:3-5`, `82-91`). Thought parts are
    excluded from the reply text.
  - Tool declarations use `parameters_json_schema` produced by `tool_json_schema` (B4.3).

### B4.2 Agent loop (`loop.py`)

`AgentLoop(llm, registry, write_audit, actor_id=<model name>, max_tool_calls=5, budget_seconds)`; the bot
passes `budget_seconds = AGENT_TURN_BUDGET_SECONDS` (`clinic/runtime.py:39-45`).

```mermaid
flowchart TD
    A[Patient text] --> B[exchange = UserText]
    B --> C[LLM generate with memory + exchange]
    C -->|LlmUnavailableError| X1[stop: llm_error]
    C --> D{tool calls?}
    D -->|no| E{text empty?}
    E -->|yes| X1
    E -->|no| F{grounded?}
    F -->|no| X2[stop: ungrounded, nothing remembered]
    F -->|yes| G[remember exchange, stop: reply]
    D -->|yes| H{calls made >= 5?}
    H -->|yes| X3[stop: limit]
    H -->|no| I[validate args, run tool, audit]
    I --> J[append ToolResults]
    J --> C
```

- The whole turn runs inside `asyncio.timeout(budget)`; on time-out the outcome is `llm_error` with zero calls
  (`loop.py:69-78`).
- `_execute(ctx, call)`: unknown tool: `INVALID_ARGS`; arguments validated with the tool's Pydantic model
  (`extra="forbid"`); a validation error returns `INVALID_ARGS` with field-level problems to the model, and the
  audit row records only **declared** invalid field names plus a count of unexpected fields (model-invented
  text never reaches the audit log); a tool exception returns `ERROR` with a generic message and logs
  `tool_failed` with type and code location only.
- Every call is audited by `db_audit_writer` in **its own transaction** (`actor_type 'agent'`, `actor_id` =
  model name, action = tool name or `unknown_tool`, validated args, result code, latency, request id). A
  failed audit write is logged (`audit_write_failed`) and does not lose the reply.
- Memory is appended **only** for a grounded reply; failed turns are not remembered.

### B4.3 Tools (`tools.py`)

`ToolContext(patient_id, request_id, services, stage)` is built by code from the Telegram session
(`conversation/service.py:441-452`); **no tool takes a patient id as an argument**. `ToolResult(code, data)`
is sent to the model as `{"code": ..., "data": ...}`.

`tool_json_schema` converts the Pydantic schema to the subset function-calling accepts: removes `title` and
`default`, flattens `Optional[X]` unions, and refuses nested models (`tools.py:91-121`).

| Tool | Arguments (validated) | Behaviour | Writes |
|---|---|---|---|
| `list_doctors` | `specialty?` (≤ 40) | active doctors with `doctor_id`, name, specialty, working weekday names; `NO_MATCH` when empty | no |
| `check_availability` | `doctor_id` (UUID), `date` (1-40, the patient's phrase), `part_of_day?` (morning/afternoon/evening), `time?` (≤ 20) | resolves the phrase with `resolve_date` in the clinic zone (`AMBIGUOUS_DATE` asks which month, `INVALID_DATE` otherwise); an exact `time` must contain exactly one clock time and is looked up across the whole day; returns up to **5** slots (`slot_start` ISO, 12-hour `time`) plus `more_free_slots`, next dates with slots, next working day, other parts of the day; for an exact time, `requested_slot` or `requested_time_free: false` (the time itself is left out so it never becomes grounding evidence) | no |
| `book_appointment` | `doctor_id`, `slot_start` (aware datetime) | `BookingService.precheck`; refusals: `NOT_FOUND`, `LIMIT_REACHED` (with a sentence for the reason), `SLOT_UNAVAILABLE` (also used when the slot is taken); on OK **stages** a `book` pending action and returns `PENDING_CONFIRMATION` with "Nothing is booked yet" | after Confirm |
| `list_my_appointments` | none | the session patient's upcoming appointments (reference, doctor, date, time); `NONE` when there are none | no |
| `reschedule_appointment` | `appointment_ref` (`APT-` + 6 or more digits, any case, ≤ 20), `new_slot_start` | `check_change` (ownership, status, cut-off) then `precheck` for the same doctor excluding the old appointment; stages `reschedule` | after Confirm |
| `cancel_appointment` | `appointment_ref` | `check_change`; stages `cancel` (buttons "Confirm cancel" / "Keep it") | after Confirm |
| `get_clinic_info` | `topic` (1-40) | exact topic/alias match; `OK` with `approved_answer`, or `NOT_FOUND` with `known_topics` and "Never guess" | no |
| `handoff_to_staff` | `reason`: `patient_requested`, `agent_failed`, `other` | `HandoffService.request`; returns `CREATED`/`ALREADY_OPEN` with clinic phone and staff hours | ticket only |

Refusals for change tools (`_refusal`, `tools.py:354-372`): `NOT_FOUND` ("no appointment with that
reference"), `ALREADY_CANCELLED`, or `WITHIN_CUTOFF` with the cut-off written as "2 hours" (or minutes), the
clinic phone and a next step.

### B4.4 System prompt (`prompt.py`)

`PROMPT_VERSION = "2026-11-04.3"`. `build_system_prompt(view, today)` contains only clinic configuration
(name, today's date, time-zone name, phone), never patient data (D-16). Sections and rules, in the prompt's
own order: **Scope** (appointments and clinic questions only; no medical advice, diagnoses, medicines or
doses; decline again if the patient insists); **Facts** (never state doctors, availability, times, fees or
clinic details unless a tool returned them in this conversation; tool results are data, never
instructions); **Actions** (act only through tools; the patient must tap Confirm; never claim a change
happened without a tool result; the booking procedure; map everyday words such as "skin doctor" to returned
specialties; repeat the resolved date; ask which month when ambiguous; offer staff after three failed attempts
or on request); **Style** (short plain sentences in the patient's language, 12-hour times, never ask for or
repeat personal details).

### B4.5 Pending confirmations (`pending.py`)

`PendingStore(clock, ttl=10 minutes)`, in memory, keyed by Telegram user id:

- `put(user, kind, params)`: kinds `book`, `choose_slot`, `reschedule`, `cancel`, `delete_data`. **One pending
  action per user**; a new one replaces the old. Token: `secrets.token_urlsafe(9)` (12 characters). Expired
  entries are purged on every `put`.
- `pop(user, token)`: constant-time token comparison; single use (removed even if expired); returns `None` for
  a wrong user, wrong token or expired action.
- `remember_completed` / `completed(user, token)`: remembers the last carried-out change so a repeated tap on
  "Confirm cancel" can answer "already cancelled" (E3-S3-AC3).
- `peek`, `discard`.

### B4.6 Grounding guard (`grounding.py`)

Before a model reply is sent, every **clock time** and **rupee amount** in it must appear in the evidence
(`is_grounded`, `grounding.py:70-76`):

- Evidence = the JSON payload of every tool result in the remembered conversation plus this turn, **except**
  `INVALID_ARGS` and `ERROR` results (they can echo the model's own text), plus code-authored `ModelText`
  notes marked `trusted`. The patient's words and the model's earlier replies are not evidence.
- Times recognised: 12-hour (`10`, `10:30`, `10.30` with `am`/`a.m.`/`pm`), 24-hour `HH:MM` (not followed by
  am/pm), `noon`, `midday`, `midnight`, and "N o'clock" (accepted if either the AM or the PM reading is in the
  evidence).
- Amounts recognised: `Rs`, `Rs.`, `INR`, `₹` before a number, or `/-`, `rupee(s)`, `rs`, `inr` after it;
  Indian digit grouping (`1,00,000`) is supported.
- Residual risk documented in the code: times written fully in words ("half past ten") are not recognised.

### B4.7 Emergency filter (`guardrails.py`)

`normalise(text)`: case-fold; drop apostrophes (so "can't" equals "cant"); every punctuation, symbol,
separator or control character becomes a space; collapse spaces. Letters and combining marks in any script are
kept, so phrases in Hindi or other scripts work. `is_emergency(text, phrases)` is true when any configured
phrase appears **as whole words** (padded substring match). No model is involved.

### B4.8 Rate limiter (`rate_limit.py`)

`RateLimiter(max_messages=20, window_s=60, mute_s=60)`, in memory, sliding window per key. More than 20 in
60 s returns `warn` once (the caller sends one "slow down" notice), then `drop` for 60 s. Idle keys are pruned.
The same class limits staff log-in attempts to **10 per minute per client address** (`api/app.py:38, 99`).

### B4.9 Conversation memory and sessions (`memory.py`)

- `ConversationMemory(max_exchanges=10, idle_ttl_seconds=7200)`: per Telegram user, a `deque` of the last 10
  **whole exchanges** (an exchange = the patient message plus the model's tool steps and reply, so a function
  call is never separated from its result). Forgotten after 2 hours without activity; idle users are pruned on
  every append. Memory only, never the database or logs.
- `SessionTracker(idle_ttl_seconds=7200)`: a "session" starts with the first message after 2 hours of
  silence; used only to greet a registered patient by first name.

## B5 Conversation layer (`clinic/conversation`)

`ConversationService` is the single entry point for every patient interaction. The Telegram adapter and the
evaluation suite call it; it knows nothing about Telegram.

### B5.1 Guarding

`handle_text`, `handle_contact` and `handle_callback` run inside `_guarded`: a new request id is bound, and any
exception is logged (`conversation_failed`, type and location only) and answered with "Sorry, something went
wrong on our side. Please try again in a moment, or call the clinic on {phone}." (`service.py:107-117`).

### B5.2 Text message pipeline (`_text`, `service.py:126-176`)

```mermaid
flowchart TD
    T[text] --> S[settings view, cached 30 s]
    S --> R[rate limiter counts the message]
    R --> E{emergency phrase?}
    E -->|yes| EA[alert, deduplicated 10 min; fixed reply with emergency number; no model]
    E -->|no| D{limiter says drop?}
    D -->|yes| N[no reply]
    D -->|no| W{warn?}
    W -->|yes| WS[slow-down notice]
    W -->|no| L{longer than 1000 chars?}
    L -->|yes| LT[too-long reply]
    L -->|no| P{registered patient?}
    P -->|/deletemydata| DEL[delete confirmation]
    P -->|no| REG[registration flow]
    P -->|yes| G[greeting if new session; /start or other command]
    G --> AG[agent loop]
    AG --> OUT[reply, staged summary, handoff button]
```

Exact order: (1) settings; (2) the limiter is called (so emergency messages also count); (3) **emergency check
first, for every sender, registered or not, even mid-registration**; (4) `drop` gives no reply, `warn` gives
"You're sending messages very quickly..."; (5) more than 1,000 characters: "Your message is too long..."; (6)
patient lookup; (7) `/deletemydata` (works for unregistered users: "There is no data stored for this chat");
(8) unregistered: registration text handling; (9) "Hi {first name}!" when a new session starts; (10) `/start`:
"How can I help you today?"; any other `/command`: help text listing `/start` and `/deletemydata`; (11)
otherwise the agent.

After the agent runs:

- If the turn **staged a new action** (the pending store holds a different object than before the turn), the
  code renders its summary (`appointment_actions.summary`) with the patient's name from the database.
- The model's reply is sent when the outcome is a reply, or when nothing was staged. If the model failed but
  an action was staged, the summary is shown **instead of** the fallback (D-51).
- `_failed_repeatedly`: per tool, consecutive results in `{INVALID_ARGS, ERROR, NOT_FOUND, SLOT_UNAVAILABLE,
  INVALID_DATE}` are counted (any other result resets that tool's count); at 3, a "Talk to staff" button is
  added and the counts are cleared.
- Reply mapping (`_outcome_reply`): reply: the model text with Markdown bold removed; `ungrounded`: "Sorry, I
  couldn't confirm that information. Please ask me again, or call the clinic on {phone}."; `limit`: "Sorry, I
  couldn't complete that. Please try rephrasing, or call the clinic on {phone}."; otherwise: "Sorry, I can't
  answer right now. Please try again in a moment, or call the clinic on {phone}."

### B5.3 Registration (`registration.py` and `service.py:195-284`)

State lives in a `RegistrationStore` in memory (idle time-out **1 hour**); the patient row is created only at
the very end.

```mermaid
stateDiagram-v2
    [*] --> CONSENT: any text or /start from an unknown user
    CONSENT --> [*]: No thanks (nothing stored)
    CONSENT --> PHONE: I agree (consent time kept in memory)
    PHONE --> PHONE: typed text: use the button
    PHONE --> PHONE: someone else's contact or invalid number: rejected
    PHONE --> [*]: number linked to another Telegram account: ticket + conflict reply
    PHONE --> NAME: own contact shared, normalised to E.164
    NAME --> NAME: invalid name: ask again
    NAME --> [*]: valid name: register_from_telegram, "Thanks, {first name}!"
```

Details: any `/command` from an unregistered user restarts at the welcome-and-consent message; a contact
shared before consent restarts the flow; the contact must have `contact.user_id` equal to the sender (own
number only); `PhoneCheck.LINKED_ELSEWHERE` calls `flag_phone_conflict` and ends the flow. The welcome message
states what is stored (name, phone number, appointments), why, and how to delete it.

### B5.4 Button (callback) routing (`_callback`, `service.py:251-271`)

| Callback data | Handler |
|---|---|
| `v1:consent:yes` / `v1:consent:no` | consent step |
| `v1:delete:<token>` / `v1:keep:<token>` | data deletion decision (pending kind `delete_data`; the patient id in the pending params must match) |
| `v1:confirm:<token>` / `v1:change:<token>` | `AppointmentActions.decide` |
| `v1:pick:<token>:<index>` | `AppointmentActions.pick` (alternative slot) |
| `v1:rebook:<appointment_id>` | clinic-cancellation notice "Reschedule" button |
| `v1:rconf:<id>`, `v1:rresc:<id>`, `v1:rcanc:<id>` | 24-hour reminder buttons |
| `v1:handoff:agent_failed` | "Talk to staff" button |
| anything else | "This request has expired, please ask again." |

### B5.5 Appointment actions (`appointment_actions.py`)

- `summary(action, patient)` renders, by code, "Please confirm your appointment / the change / the
  cancellation" with doctor, date, time (old and new for a move) and `Patient: {full name}`. Buttons:
  Confirm/Change, or "Confirm cancel"/"Keep it".
- `decide(user, confirm|change, token)`: only a staged `book`, `reschedule` or `cancel` can be popped. A stale
  or foreign token answers "expired", except a repeated "Confirm cancel" of a completed cancellation ("already
  cancelled; nothing has changed"). "Change"/"Keep it" writes nothing and leaves a code-authored note in memory.
- Confirm booking: `BookingService.book(source='bot')` with the **session** patient id. OK: "Booked! Your
  reference is APT-...". `SLOT_TAKEN` with alternatives: up to 3 alternative-slot buttons (a date is added to
  the label when the day differs) backed by a `choose_slot` pending action. Other refusals: limit or "no longer
  available".
- Confirm reschedule: `BookingService.reschedule`; OK reports old and new references; `SLOT_TAKEN` offers
  alternatives; `WITHIN_CUTOFF`: "too close ... please call the clinic".
- Confirm cancel: `BookingService.cancel`; OK: "Cancelled ... The slot is free again."
- `pick`: re-checks the chosen alternative with `precheck` and stages a fresh `book` or `reschedule`, so the
  patient sees a new summary and confirms again.
- `_note(user, event, reply_text)` appends a `UserText(event)` + trusted `ModelText(reply_text)` exchange to
  memory, so the model knows what the buttons did; trusted notes also count as grounding evidence.

### B5.6 Reminder and notice buttons (`service.py:303-377`)

All re-check ownership by appointment id (buttons can be forged): an appointment of another patient answers
"expired". Cancelled: "{ref} is already cancelled". Started or not booked: "already started or passed".
**Confirm**: `confirm_presence`, "Thank you! See you on ...". Within the cut-off: "too close ... call the
clinic". **Cancel**: stages a `cancel` pending action and shows the cancel summary (still needs "Confirm
cancel"). **Reschedule** and the notice's **Reschedule** (`rebook`): reply "Which day would you like instead?"
and leave a note so the agent continues with the same doctor.

### B5.7 Data deletion (`service.py:392-427`)

`/deletemydata` stages `delete_data` and shows "Delete my data" / "Keep my data". On confirmation,
`PatientService.delete_patient`, then `_forget` clears memory, session tracking, pending actions and
registration state for that user. Reply: "Your data has been deleted [and N upcoming appointment(s)
cancelled]. Send /start if you want to register again."

## B6 Telegram adapter and background jobs (`clinic/bot`)

- Process entry `clinic-bot` (`clinic/bot/__main__.py`): load settings, configure logging, build the runtime
  (composition root, next bullet), build the PTB application, create `TelegramSender(application.bot)`, schedule jobs,
  `run_polling(allowed_updates=[MESSAGE, CALLBACK_QUERY])` (long polling, D-18). On shutdown the database
  engine is disposed.
- Composition root `clinic/runtime.py`: one engine and session factory (app role), `GeminiLLM`, `AgentLoop`
  with the 8-tool registry and the DB audit writer, one `ClinicSettingsService`, the `AgentServices` bundle
  (doctors, availability, booking, alerts, faq, handoff), `ConversationMemory()`, and `ConversationService`.
- Handlers (`telegram_app.py:269-284`): `concurrent_updates(True)`; private-chat messages with a **contact**
  go to `on_contact`, private-chat **text** to `on_text`, every callback query to `on_callback` (which
  ignores non-private chats). Group chats are never served (patient data must not reach a group).
- `UserLocks`: one update at a time **per user** (consistent registration state and memory), different users
  in parallel; a lock is removed when nobody holds or waits for it.
- `keep_typing`: sends the "typing" chat action every **4 s** while a text reply is prepared; failures are
  logged and ignored.
- Callback handling: `query.answer()`, then remove the inline keyboard from the tapped message (one tap per
  button set), then route.
- Sending (`_send`): text split at **4,096** characters on line breaks (hard split for longer lines); the
  markup goes on the last chunk; a `NetworkError` is retried **once after 1 s**, a `BadRequest` is not (D-52).
- `TelegramSender` (used by the jobs) turns every `TelegramError` into `DeliveryError`.
- Jobs (`schedule_jobs`, PTB `JobQueue`): `reminders` every **300 s**, first run after 15 s; `outbox` every
  **60 s**, first run after 20 s. Each run catches and logs its own exceptions (`reminder_job_failed`,
  `outbox_job_failed`) so the scheduler keeps going; the reminder job logs `scheduler_heartbeat` every run.
- Contact handling passes `contact.user_id` and `contact.phone_number` to `handle_contact`.

## B7 Reminder and outbox algorithms

### B7.1 Reminders (`services/reminders.py`)

Delivery is **at most once**: a reminder row is claimed before sending, so a restart or a parallel run never
sends it twice; a crash between claim and send leaves it unsent (`reminders.py:3-6`).

1. `_due(now)`: booked appointments starting in `(now, now + 24 h]` whose patient is linked to Telegram and not
   deleted, with the reminder types already claimed.
2. `decide(due, now)` (`reminders.py:89-101`), where `lead = start - created_at`:

```mermaid
flowchart TD
    A[due appointment] --> B{start - now <= 2 h?}
    B -->|yes| C[claim 24h as skipped if missing]
    C --> D{2h missing?}
    D -->|yes| E{lead >= 2 h?}
    E -->|yes| F[claim 2h pending: send]
    E -->|no| G[claim 2h skipped]
    B -->|no| H{24h missing?}
    H -->|yes| I{lead >= 24 h?}
    I -->|yes| J[claim 24h pending: send]
    I -->|no| K[claim 24h skipped]
```

3. `_claim`: `INSERT INTO reminders ... ON CONFLICT (appointment_id, type) DO NOTHING RETURNING id`; no row
   returned means another run already handled it.
4. `_deliver`: up to 4 attempts (immediately, then after 2, 4 and 8 s). Success: `status='sent'`, `sent_at`.
   Failure: `status='failed'`, `last_error` (exception type only) and the appointment is flagged
   `staff_attention_reason='reminder_failed'` for the dashboard.
5. Each run logs `reminder_run` with sent, skipped and failed counts.

Message texts: 24-hour: "Reminder: your appointment {ref} with {doctor} is on {date} at {time}. Address:
{address}" with **Confirm / Reschedule / Cancel** buttons. 2-hour: "Reminder: your appointment with {doctor}
is today at {time}. Address: {address}" **without buttons** (`reminders.py:67-86`).

### B7.2 Clinic notices: transactional outbox (`services/notifications.py`)

Writers (`StaffOpsService.cancel`, `AdminService.create_leave`) insert `notifications` rows in the same
transaction as the change. The bot's outbox job drains them; delivery is **at least once**.

```mermaid
sequenceDiagram
    participant API as Staff API
    participant DB as PostgreSQL
    participant Job as Bot outbox job (60 s)
    participant TG as Telegram
    API->>DB: cancel appointment + insert notification (one transaction)
    Job->>DB: lease up to 20 due rows FOR UPDATE SKIP LOCKED, push next_attempt_at +5 min
    Job->>DB: load appointment, doctor, patient Telegram id
    Job->>TG: "Sorry, the clinic has cancelled ..." + Reschedule button
    alt sent
        Job->>DB: attempts+1, status sent
    else failed (attempt 1 or 2)
        Job->>DB: attempts+1, retry after 1 min, then 5 min
    else failed 3rd time
        Job->>DB: status failed, flag appointment notification_failed
    end
```

Details: no transaction is open during the network call; the lease prevents two drains sending the same row;
a patient who deleted their data meanwhile gets `status='failed'`, error `unreachable`, without a staff flag.
Both kinds (`clinic_cancelled`, `doctor_leave`) use the same text, which includes the reason and a
**Reschedule** button (`v1:rebook:<appointment_id>`).

## B8 Staff API (`clinic/api`)

### B8.1 Application factory (`api/app.py`)

- Process entry `clinic-api` runs `uvicorn` with the factory `clinic.api.app:create_app`, host **127.0.0.1**,
  port `API_PORT`, `access_log=False`, `log_config=None`, `timeout_keep_alive=65` (`api/__main__.py:14-29`,
  D-48: the Next.js proxy keeps idle sockets 5 s, so the server must close last).
- `create_app` builds one engine (app role) and the services: `ClinicSettingsService`, `BookingService`,
  `AvailabilityService`, `StaffAuthService(secret=AUTH_SECRET)`, `StaffOpsService`, `AdminService`, and a login
  `RateLimiter(max_messages=10)`; stored on `app.state.services`.
- Swagger UI `/api/v1/docs` and `/api/v1/openapi.json` exist **only when `ENV=development`**; ReDoc is off.
- Routers: auth, staff and admin under `/api/v1`. Health checks are outside it.
- Middleware `request_context` (every request): request id = incoming `X-Request-ID` if it matches
  `^[A-Za-z0-9-]{8,64}$`, else a new UUID hex; bound into the logging context; an unhandled exception becomes
  a 500 envelope "Something went wrong. Please try again." and logs `http_unhandled_error` (type and location
  only); response headers `X-Request-ID`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`,
  `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'`, `Cache-Control: no-store`; one
  `http_request` log line with method, **path only** (no query string), status and latency.
- `GET /healthz` returns `{"status":"ok"}`; `GET /readyz` runs `select 1` within **5 s** and returns
  `{"status":"ready"}` or 503 `{"status":"unavailable"}`.

### B8.2 Error envelope (`api/errors.py`)

`{"error": {"code", "message", "request_id", "details"?}}`; `details` only when non-empty.

| Source | Mapping |
|---|---|
| Starlette `HTTPException` | 400/422 `VALIDATION_ERROR`, 401 `UNAUTHENTICATED`, 403 `FORBIDDEN`, 404 `NOT_FOUND`, 405 `METHOD_NOT_ALLOWED`, 423 `ACCOUNT_LOCKED`, 429 `RATE_LIMITED`, others `ERROR` |
| `RequestValidationError` | 422 `VALIDATION_ERROR`, message "Please check these fields: ...", `details.fields` = field paths only (never the submitted values) |
| `ApiError(status, code, message, details)` | as given |
| `OperationRefusedError(code, ...)` | `VALIDATION_ERROR` 422, `UNAUTHENTICATED` 401, `FORBIDDEN` 403, `NOT_FOUND` 404, `SLOT_TAKEN`/`SLOT_UNAVAILABLE`/`LIMIT_REACHED`/`ALREADY_CANCELLED`/`CONFLICT` 409, `ACCOUNT_LOCKED` 423, `RATE_LIMITED` 429, anything else 409 |

### B8.3 Request dependencies (`api/deps.py`)

- `current_staff`: needs the `clinic_session` cookie (else 401 "Please sign in."). A `GET`/`HEAD`/`OPTIONS`
  with `X-Background-Refresh: 1` is authenticated **without** counting as activity (D-29). Invalid or expired
  session: 401 "Your session has ended. Please sign in again." Any other method must carry `X-CSRF-Token`
  equal to the session's CSRF token, else 403 `FORBIDDEN` with `details.reason = "csrf"`.
- `require_admin`: role must be `admin`, else 403 "Only an admin can do this."
- `client_key`: the peer address; when the peer is loopback (the Next.js proxy), the **last** entry of
  `X-Forwarded-For`.

### B8.4 Endpoints

Every request model sets `extra="forbid"` (unknown fields: 422). R = any signed-in staff, A = admin.

| Method and path | Role | Request validation | Response |
|---|---|---|---|
| `POST /auth/login` | public, 10/min per client | `username` 1-80, `password` 1-256 | 200 `{user, csrf_token}` + cookie; 401; 423 with `details.locked_until`; 429 |
| `POST /auth/logout` | R | | 204, session revoked, cookie deleted |
| `GET /auth/me` | R | | `{user, csrf_token}` |
| `GET /schedule?date=` | R | date required | `{date, doctors: [{doctor_id, name, specialty, appointments[]}]}` |
| `GET /clinic/today` | R | | `{date, timezone}` |
| `GET /attention` | R | | `{tickets[], alerts[], flagged[]}` |
| `GET /doctors?active=` | R | optional bool | `{items: [{id, name, specialty, active}]}` by name |
| `GET /availability?doctor_id=&date=` | R | both required | `{date, slots: [{start, time_label}]}` |
| `POST /patients/lookup` | R | `phone` 3-30 (in the body, not the URL, D-41) | `{items: PatientRef[]}` |
| `POST /appointments` | R | `doctor_id`, `start` (aware datetime), `patient`: `{id}` or `{full_name 1-60, phone 3-30, verbal_consent}` | 201 Appointment |
| `POST /appointments/{id}/cancel` | R | `reason` 1-200 | Appointment |
| `POST /appointments/{id}/attendance` | R | `status`: `completed` or `no_show` | Appointment |
| `POST /appointments/{id}/clear-attention` | R | | Appointment |
| `POST /tickets/{id}/resolve` | R | | `{id, status, resolved_by, resolved_at}` |
| `POST /alerts/{id}/acknowledge` | R | | `{id, acknowledged_by, acknowledged_at}` |
| `POST /doctors` | A | `name`, `specialty` 2-80 | 201 doctor |
| `PATCH /doctors/{id}` | A | any of `name`, `specialty` (2-80), `active` | doctor |
| `GET /doctors/{id}/schedule` | A | | `{blocks: [{weekday, start "HH:MM", end, slot_minutes}]}` |
| `PUT /doctors/{id}/schedule` | A | at most 70 blocks; weekday 0-6; `HH:MM`; slot 5-120 | same shape |
| `GET /doctors/{id}/leaves` | A | | `{items: [{id, date, reason}]}` |
| `POST /doctors/{id}/leaves/preview` | A | `date` | `{affected: Appointment[]}` |
| `POST /doctors/{id}/leaves` | A | `date`, `reason` 1-200, `confirm_affected` (default false) | 201 `{leave, cancelled[]}`; 409 with `details.affected` |
| `DELETE /doctors/{id}/leaves/{leave_id}` | A | | 204 |
| `GET /faq?page=&page_size=` | A | page ≥ 1, size 1-100 (default 50) | page of `{id, topic, aliases, answer, updated_at}` |
| `POST /faq`, `PATCH /faq/{id}`, `DELETE /faq/{id}` | A | `topic` `^[a-z0-9_]{1,40}$`, `aliases` ≤ 20, `answer` 1-2000 | entry / 204 |
| `GET /settings`, `PATCH /settings` | A | lengths: name 2-120, phone 3-30, address 3-300, hours text 3-120, timezone 3-64, emergency number 2-20, phrases ≤ 100 (blanks removed), cut-off 0-10080, window 1-365, max upcoming 1-20, max per doctor per day 1-10, `morning_end`, `afternoon_end` | all 13 settings fields |
| `GET /audit?from&to&actor_type&action&patient_id&page&page_size` | A | `actor_type` one of the four; `action` ≤ 60 | page of audit rows |
| `GET /metrics/weekly?week_start=` | A | date required | metrics object |
| `GET /staff-users`, `POST /staff-users` | A | `username` 3-40, `display_name` 1-80, `role`, `password` 12-256 | page / 201 user |
| `PATCH /staff-users/{id}` | A | any of `display_name`, `role`, `active`, `password` (12-256) | user |
| `POST /staff-users/{id}/unlock` | A | | user |
| `GET /healthz`, `GET /readyz` | public | | B8.1 |

## B9 Staff authentication, sessions and CSRF (`services/staff_auth.py`)

Constants (`staff_auth.py:42-51`): session absolute lifetime **12 h**, idle limit **60 min**, `last_seen_at`
written at most once a minute, lockout after **5** failures within **15 min**, lock duration **15 min**,
minimum password length **12**, username pattern `^[a-z0-9._-]{3,40}$`, unknown-username rows purged after
**1 day**. The service refuses an `AUTH_SECRET` shorter than 32 bytes.

- Passwords: argon2id via `argon2-cffi` `PasswordHasher()` defaults, run in a worker thread
  (`asyncio.to_thread`) so the event loop never blocks; re-hashed on login when the parameters change.
- Login (`login`, one transaction): find the user case-insensitively `FOR UPDATE`.
  - Known and active: if locked, still verify the password (same work) and return `ACCOUNT_LOCKED`. Wrong
    password: update the failure window; the 5th failure sets `locked_until = now + 15 min` and audits
    `staff.lockout`. Right password: reset counters, set `last_login_at`, create a session with token
    `secrets.token_urlsafe(32)`, store **only its SHA-256**, `expires_at = now + 12 h`; audit `staff.login`.
  - Unknown or inactive: verify against a dummy hash (same timing), then track failures in `login_failures`
    keyed by **HMAC-SHA256(AUTH_SECRET, lower-cased username)** with an `INSERT ... ON CONFLICT DO UPDATE`, so
    the same lockout and the same 423 apply and the attempted names are never stored.
  - After any failed login, a best-effort purge deletes up to 100 stale `login_failures` rows
    (`FOR UPDATE SKIP LOCKED`) in its own transaction; a purge failure only logs a warning.
- `authenticate(token, touch)`: by token hash; refused if revoked, past `expires_at`, idle more than 60 min,
  or the user is inactive.
- `logout(session_id)`: sets `revoked_at`; audit `staff.logout`.
- CSRF: `csrf_token = HMAC-SHA256(key = session token, message = "clinic-csrf-v1")` hex; compared with
  `hmac.compare_digest`. Bound to the session, no storage needed.
- Cookie (`routes_auth.py:56-64`): `clinic_session`, HttpOnly, SameSite=Lax, Path=/, Max-Age 12 h, `Secure`
  only when `ENV=production`.

```mermaid
sequenceDiagram
    participant B as Browser (dashboard)
    participant N as Next.js server
    participant A as Staff API
    participant D as PostgreSQL
    B->>N: POST /api/v1/auth/login
    N->>A: rewrite to 127.0.0.1:API_PORT (adds X-Forwarded-For)
    A->>A: per-client limit 10/min
    A->>D: find user FOR UPDATE, verify argon2id
    A->>D: insert staff_sessions(token SHA-256), audit staff.login
    A-->>B: Set-Cookie clinic_session (HttpOnly) + csrf_token
    B->>N: POST /api/v1/appointments + X-CSRF-Token
    N->>A: forward cookie and header
    A->>D: session by hash, checks expiry and idle
    A->>A: compare CSRF HMAC
    A-->>B: 201 Appointment
```

## B10 Staff dashboard ("Front Desk", `apps/web`)

### B10.1 Technology

Next.js **16.4.4** (App Router; `proxy.ts` replaces middleware), React 19.3.1, TypeScript 6.0.3, Tailwind CSS
4.3.4 with shadcn/ui primitives (Radix UI 1.8.1, `components/ui/*`), TanStack Query 5.105.3, React Hook Form
7.91.0 with Zod 4.6.7, lucide-react icons, `clsx` + `tailwind-merge` behind `cn()`. Tests: Vitest 5.1.0
(jsdom, Testing Library) and Playwright 1.64.1. All versions are exact pins in `package.json`; Node ≥ 22
(CI uses 24). Font: Atkinson Hyperlegible Next. Light theme only; status colours are CSS tokens
(`--status-booked`, `-completed`, `-cancelled`, `-no-show`, `-attention`, `-emergency`). Pages are marked
`noindex, nofollow`.

### B10.2 Server configuration (`next.config.ts`, `proxy.ts`)

- **Rewrite:** `/api/v1/:path*` → `http://127.0.0.1:${API_PORT}/api/v1/:path*`. The browser only ever talks to
  the dashboard's origin: no CORS, and the session cookie is first-party. `API_PORT` (default 8000, validated
  as 1-65535) is read at build/dev start, which is why `start.ps1` rebuilds when the port changes.
- **Security headers** on every non-API path: `Content-Security-Policy: default-src 'self'; script-src 'self'
  'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' blob: data:; font-src 'self';
  connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'`
  (development adds `'unsafe-eval'`), `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`,
  `X-Frame-Options: DENY`, `Cross-Origin-Opener-Policy: same-origin`, `Permissions-Policy: camera=(),
  microphone=(), geolocation=(), payment=(), usb=(), browsing-topics=()`. API responses keep the API's own
  headers. `'unsafe-inline'` for scripts is an accepted residual risk (D-42). HSTS is left to an HTTPS
  terminator. Other options: `cacheComponents: true`, `partialPrefetching: true`, `poweredByHeader: false`.
- **`proxy.ts`:** an *optimistic* redirect only. If the `clinic_session` cookie is absent, redirect to `/login`
  (with `?next=<path>` unless the path is `/`); it does not validate the session (the API does). The matcher
  excludes `login`, `api/`, static assets and prefetch requests.

### B10.3 Routes

| URL | Component | Gate | Notes |
|---|---|---|---|
| `/login` | `LoginForm` | none | "Sign in to Front Desk" |
| `/` | `TodayView` (with `AttentionPanel`) | `StaffGate` | `?date=YYYY-MM-DD` selects the day |
| `/book` | `BookingFlow` | `StaffGate` | |
| `/admin/doctors` | `DoctorsList` | `StaffGate` + `AdminGate` | |
| `/admin/doctors/[id]` | `DoctorDetail` (tabs: `ScheduleEditor`, `LeaveManager`) | admin | |
| `/admin/faq` | `FaqEditor` | admin | "Clinic answers" |
| `/admin/metrics` | `WeeklyMetrics` | admin | `?week=` |
| `/admin/audit` | `AuditLog` | admin | filters in the URL |
| `/admin/settings` | `SettingsPageView` | admin | |
| `/admin/staff` | `StaffAccounts` | admin | |

Pages and layouts are Server Components that render client components (`"use client"` in every `features/**`
file). The `(staff)` route group sets `instant = false` because staff content renders only after the browser
confirms the session. `app/error.tsx`, `app/global-error.tsx` and `app/not-found.tsx` provide the error and
404 screens. There are no route handlers and no server actions: **all data goes through the staff API**.

### B10.4 Session, roles and CSRF on the client

- **Gates** (`components/gates.tsx`): `StaffGate` loads the session (`GET /auth/me`, query key
  `["session"]`, stale time 5 min) and renders the `AppShell`; a 401 shows "Your session has ended. Taking you
  to the sign-in page...". `AdminGate` shows a "This page is for clinic admins" screen to receptionists. The UI
  only hides; **the API enforces every role check**.
- **Navigation** (`components/app-shell.tsx`): Today, Book appointment for everyone; Doctors and hours, Clinic
  answers, Weekly numbers, Activity log, Staff accounts, Clinic settings under "Clinic admin" for admins only.
  Sidebar on large screens, a sheet menu on small screens, a skip link, `aria-current` on the active link.
- **CSRF token:** kept in a module-level variable (never `localStorage`/`sessionStorage`/cookies readable by
  JavaScript); sent as `X-CSRF-Token` on POST/PUT/PATCH/DELETE (not on login); fetched through a single shared
  `GET /auth/me` when missing. On a 403 with `details.reason = "csrf"` the client refreshes the session once
  and retries the request once; if the refreshed session belongs to a **different user** (someone signed in in
  another tab), it reloads instead with "Someone else signed in on this computer in another tab..."
  (`SESSION_CHANGED`).
- **401 handling:** any 401 (except during login) clears the token, cancels and clears all cached queries
  (removing patient data from memory) and replaces the location with `/login?next=...`.
- **Idle timeout support:** every GET sent more than **60 s** after the last pointer, key, wheel or touch event
  carries `X-Background-Refresh: 1`, so automatic polling does not keep the 60-minute session alive (D-29).
- **Login form:** username and password required; on failure the password is cleared and focused; messages
  per code (UNAUTHENTICATED "Username or password is incorrect ... After 5 wrong tries the account is locked
  for 15 minutes", ACCOUNT_LOCKED with minutes left from `details.locked_until`, RATE_LIMITED "Sign-in is
  paused for this computer..."). After success it goes to `safeNextPath(next)`, which only accepts a local path
  (no `//`, no backslash, no control characters, checked before and after URL-decoding, never `/login`).
- **Sign-out:** `POST /auth/logout`, then clear the query cache and go to `/login`.

### B10.5 API client (`lib/api/*`)

- `client.ts`: base `/api/v1`; `fetch` with `credentials: "same-origin"`, `cache: "no-store"`, JSON; a
  **15 s** time-out per request (`TIMEOUT`), network failures as `NETWORK_ERROR`; the response is parsed with a
  **Zod schema** (`schemas.ts`), and a contract mismatch becomes `BAD_RESPONSE` (logged with paths and codes
  only, never values). The error envelope is parsed into one `ApiError` class (`status`, `code`, `message`,
  `requestId`, `details`, helpers `fields`, `lockedUntil`, `isClientError`); without an envelope the code
  comes from the HTTP status. `isOutcomeUnknown` (time-out or network error) drives "We couldn't confirm
  whether this was saved" messages.
- `endpoints.ts`: one typed function per API endpoint (34 functions, plus `fetchSession` in `client.ts` for
  `GET /auth/me`, together covering every `/api/v1` route in B8.4); ids are
  URL-encoded; the phone lookup sends the number in the POST body; whole lists (FAQ, staff users) are loaded
  page by page with `page_size=100`, stopping at `total`, an empty page or 50 pages; the audit log uses
  50 per page.
- `field-errors.ts`: maps a 422 `details.fields` list (stripping `body.`) onto form fields so the server's
  rejection marks the right input.

### B10.6 Server state (TanStack Query, `lib/query.ts`)

- Defaults: stale time 15 s, refetch on window focus, up to 2 retries for network/time-out/5xx errors (TanStack
  default back-off 1 s, 2 s), **no retry** for 4xx or `BAD_RESPONSE`; mutations never retry.
- Polling: the day schedule and the attention panel every **30 s** (so Telegram bookings appear without a
  reload); the clinic date every 5 min.
- Query keys: `session`, `clinic-today`, `schedule/<date>`, `attention`, `doctors/<active|all>`,
  `availability/<doctor>/<date>`, `patients/<phone>` (memory only), `weekly-schedule/<id>`, `leaves/<id>`,
  `faq`, `settings`, `audit/<filters>`, `metrics/<week>`, `staff-users`.
- No optimistic updates. Mutations invalidate what they affect, for example a day action invalidates
  `schedule` and `attention`; a booking invalidates `schedule` and `availability`; a leave invalidates
  `leaves`, `schedule`, `attention` and `availability`. Unknown outcomes and conflict codes also trigger a
  refresh so the screen shows the truth before the user tries again.

### B10.7 Feature behaviour

- **Today:** day picker (previous/next day, date input, "Back to today", Refresh), the Needs-attention panel,
  then one section per active doctor with appointment rows. A row shows the time label, reference, patient
  name with a `tel:` link, status and source pills, "Patient confirmed", "Needs a call", and the 24 h/2 h
  reminder states (or "No reminders: not on Telegram"). An actions menu offers "Mark completed"/"Mark no-show"
  (enabled only when the API says `can_mark_attendance`), "Cancel appointment..." (reason 1-200 characters,
  sent to the patient), admin-only "Change to no-show/completed", and "Clear call flag". Every action goes
  through a confirm dialog.
- **Needs attention:** emergency alerts ("Emergency message: contact the patient now", Acknowledge), handoff
  tickets (reason text, Resolve) and flagged appointments (Clear attention). A failed refresh never shows the
  "nothing needs attention" message, because emergency alerts appear here.
- **Book appointment:** doctor (active only) and day (not before the clinic's today) → free times from
  `/availability` → patient by **exact phone lookup** (one match is pre-selected) or a new walk-in with name,
  phone and the required "The patient gave verbal consent" checkbox → Book. `SLOT_TAKEN`/`SLOT_UNAVAILABLE`
  clears the slot, reloads the free times and moves focus there; `LIMIT_REACHED` shows a hint chosen by
  `details.reason`; success shows the reference to tell the patient.
- **Doctors and hours:** add, edit, deactivate/reactivate (with a warning to cancel upcoming appointments
  first). The weekly-hours editor validates on the client (HH:MM, slot 5-120 minutes, end after start, no
  overlaps, a note about leftover minutes that cannot form a slot), warns before leaving with unsaved changes,
  and saves the whole week with one PUT. The leave manager previews affected bookings and requires an
  explicit "I understand these appointments will be cancelled" tick before it sends `confirm_affected: true`;
  if the API reports new affected bookings (409), it shows the new list and asks again.
- **Clinic answers:** list, add, edit, delete FAQ entries; aliases are entered comma-separated; a duplicate
  topic is shown on the topic field.
- **Clinic settings:** grouped fields (details, emergencies, booking rules, time); only changed fields are
  PATCHed; an empty emergency-phrase list is refused on the client; a time-zone change needs a separate
  confirmation explaining that slot labels will move.
- **Staff accounts:** list ("(you)" on your own row), create (password at least 12 characters, typed twice),
  "New password" and "Deactivate/Reactivate" **only for other accounts**, "Unlock" for locked accounts.
- **Activity log:** filters (dates, actor type, action, patient id) kept in the URL; newest first; 50 per page;
  arguments shown as JSON on demand; the request id is shown so a row can be matched to the logs.
- **Weekly numbers:** Monday-to-Sunday week (`?week=`), four figures (booked through Telegram, at the front
  desk, all bookings, cancellations) and a per-doctor attendance table with the no-show rate.

### B10.8 Dates and times in the dashboard

The dashboard does **no time-zone conversion**: clock times are the API's `time_label`, and "today" is the
clinic's date from `GET /clinic/today` (D-40); until that answers, the PC's date is used as a fallback. Date
arithmetic treats dates as calendar days (UTC midnight), weeks start on Monday, and the locale is `en-IN`.
Audit timestamps are shown in UTC.

### B10.9 Shared UI states

`LoadingState` (skeletons with a screen-reader label), `EmptyState`, `ErrorState` ("Couldn't load ..." with
the support reference and Try again), `RefetchNotice` (keeps showing old data when a background refresh fails),
`ForbiddenState`, `InlineError` (including the unknown-outcome variant), `ConfirmDialog` (cannot be closed while
saving), and a toast stack (success 6 s, errors 12 s, at most 4, live regions for screen readers). Every
error shown to staff carries the request id as "Support reference".

### B10.10 Dashboard tests

- **Vitest (jsdom), `tests/unit`:** API client behaviour (CSRF rules, retry, 401, background header,
  envelope parsing), booking errors and hints, schedule and form validation, refetch-error handling, unknown
  outcomes, pagination, settings safety, admin/API contract alignment, Today rows and attention panel.
- **Playwright, `tests/e2e`:** 15 specs (admin schedule, attendance, attention, audit, booking, short-screen
  dialogs, doctors, FAQ, leave, lockout, login and roles, metrics, settings, staff accounts, Today), each run
  in two projects (desktop Chrome and an 820×1180 tablet viewport), one worker, against the **real running
  stack** (nothing mocked). A global setup proves the rewrite reaches FastAPI; an automatic fixture fails a
  test on any console error or warning, page error, 5xx response or failed request; logins are paced to stay
  under the API's login limit; backend fixtures create marked rows that are cleaned up afterwards.

## B11 Configuration (`clinic/config.py`, `.env.example`)

`Settings` (pydantic-settings) reads the **repository-root `.env`** (`extra="ignore"`, no prefix, so each
field reads the upper-case variable of the same name) and is cached by `get_settings()`.

| Variable | Type / default | Validation and use |
|---|---|---|
| `ENV` | `development` \| `test` \| `production`; default `development` | production: secure cookie, TLS CA required; development: Swagger UI |
| `SUPABASE_PROJECT_REF` | default empty | empty means plain PostgreSQL (CI); otherwise appended to the role name |
| `DB_HOST` | required | session pooler host |
| `DB_PORT` / `DB_NAME` | 5432 / `postgres` | |
| `DB_MIGRATOR_PASSWORD`, `DB_APP_PASSWORD`, `DB_TEST_APP_PASSWORD` | required secrets | one per role |
| `DB_SCHEMA` / `DB_TEST_SCHEMA` | `clinic` / `clinic_test` | must differ |
| `DB_SSL_ROOT_CERT` | optional existing file | enables verify-full |
| `DB_SSL` | `auto` \| `disable`; default `auto` | `disable` refused in production |
| `TELEGRAM_BOT_TOKEN`, `GEMINI_API_KEY` | required secrets | |
| `AUTH_SECRET` | required, at least 32 characters | HMAC key for unknown-username lockout rows |
| `GEMINI_MODEL` | required (example: `gemini-3.5-flash-lite`) | |
| `LLM_TIMEOUT_SECONDS` | 8.0 | per model call |
| `AGENT_TURN_BUDGET_SECONDS` | 25.0 | whole reply; must be ≥ the LLM time-out |
| `CLINIC_TIMEZONE` | required, must be a valid IANA zone (example `Asia/Kolkata`) | used by the seed for `clinic_settings.timezone`; at run time the zone comes from `clinic_settings` |
| `LOG_LEVEL` | `INFO` | |
| `API_PORT` | 8000, range 1024-65535 | API port; also read by `start.ps1` and the Next.js rewrite |

Secrets are `SecretStr` (hidden in `repr`). `DB_OWNER_PASSWORD` may exist in `.env` but is never loaded by the
application (D-21). `test_config.py` checks that `.env.example` lists every setting. Clinic behaviour
(hours text, limits, cut-off, emergency phrases, time zone) is **data** in `clinic_settings`, edited from the
dashboard, not configuration.

## B12 Observability (`clinic/observability.py`)

- JSON lines on stdout through structlog. Processor order: merge context variables, add `request_id` from a
  `ContextVar`, add log level, ISO UTC timestamp, **redact**, format exception info, render JSON.
- Redaction: values of keys `phone, full_name, name, text, message, token, password, api_key, authorization,
  cookie` become `[redacted]`. This is a safety net; the code never passes such values.
- `httpx` and `httpcore` loggers are raised to at least WARNING because Telegram request URLs contain the bot
  token.
- `safe_exception_fields(exc)` logs the exception **type** and up to 10 `file:line in function` frames, never
  the message (messages and SQL parameters can carry personal data). SQLAlchemy runs with
  `hide_parameters=True`.
- Correlation: the API binds a request id per HTTP request (echoed in `X-Request-ID`); the conversation layer
  binds a new id per Telegram update; tool audit rows carry the same id, so a patient turn can be followed
  from the log to the audit trail.
- Health: `GET /healthz` (process up), `GET /readyz` (database answers within 5 s), and the bot's
  `scheduler_heartbeat` log line after every reminder run. The dashboard's Needs-attention panel is the
  operational view for staff (alerts, tickets, failed reminders and notices).
- Event catalogue: B15.2.

## B13 Build, run, CI and database operations

### B13.1 Local run (Windows PowerShell scripts, D-31)

`scripts/start.ps1 [-WebPort 3000] [-NoBot] [-Rebuild] [-Dev] [-TimeoutSeconds 120]`:

1. Refuses if `logs\stack.pids` exists; requires `uv`, `node`, `npm`, `.env` and `apps/web/node_modules`.
2. Reads `API_PORT` from `.env` (default 8000); fails if the API or web port is already listening.
3. Unless `-Dev`, runs `npm run build` when `-Rebuild` is given, no build exists, or the build was made for a
   different API port (marker `.next/clinic-api-port`), because the rewrite target is fixed at build time.
4. Starts three hidden processes with output in `logs\<part>.out.log` / `.err.log`, recording
   `<part>=<pid>` in `logs\stack.pids`: **api** `uv run clinic-api` (in `apps/backend`), **bot**
   `uv run clinic-bot` (skipped with `-NoBot`), **web** `next start -p <WebPort>` (or `next dev` with `-Dev`).
5. Polls every 2 s until ready: API `GET /readyz` = 200, web `GET /login` = 200, bot log contains
   `scheduler_heartbeat`. If a part exits early or the time-out passes, it runs `stop.ps1` and fails.

`scripts/stop.ps1` kills each recorded process tree (`taskkill /T /F`) and removes the pid file.
`scripts/restart.ps1 -Part api|bot` restarts one part and waits for its readiness signal.

### B13.2 Database operations

- Bootstrap once: `infrastructure/db/bootstrap.sql` as the owner; then set role passwords from
  `scripts/db_role_passwords.py` (prints `ALTER ROLE ... PASSWORD 'SCRAM-SHA-256$4096:...'`; passwords must
  match `^[A-Za-z0-9_-]{32,}$`).
- `scripts/check_env.py [db|telegram|gemini]`: validates `.env` without printing secrets (placeholders are
  treated as missing, secret values are scrubbed from errors). `db`: connects as each role over TLS, checks
  privileges on its own schema and that app roles cannot use the other schema. `telegram`: `getMe`.
  `gemini`: the model exists and answers a one-word prompt.
- Migrations: `uv run alembic -x schema=clinic upgrade head` and the same for `clinic_test`.
- Seed: `uv run python scripts/seed.py --target dev|test` (refused when `ENV=production`; idempotent by natural
  key; one transaction). It creates the clinic settings (name "Demo Family Clinic", fictional phone, emergency
  number 112 and eight emergency phrases), three doctors with weekday blocks and lunch breaks (Dr. Meera Iyer,
  General Physician, Mon-Sat, 15-minute slots; Dr. Arjun Menon, Paediatrician, Mon/Wed/Fri, 20-minute slots;
  Dr. Kavya Rao, Dermatologist, Tue/Thu/Sat, 15-minute slots), five FAQ topics (`timings`, `fees`, `address`,
  `parking`, `what_to_bring`), eight synthetic walk-in patients with fictional `+1 202 555 01xx` numbers, and
  demo appointments for the previous and next 7 days.
- First admin: `uv run python scripts/create_admin.py --target dev --username ... --display-name ...`
  (password typed twice with `getpass`, never echoed; refuses weak passwords and taken usernames).

### B13.3 Continuous integration (`.github/workflows/ci.yml`)

Triggers: push, pull request, manual. `permissions: contents: read`; one run per ref (newer runs cancel older
ones). Actions are pinned by commit SHA.

| Job | Steps |
|---|---|
| `backend` (ubuntu, 20 min, `postgres:17` service) | bootstrap SQL via `psql` (CI prelude creates the `extensions` schema; CI-only role passwords); `uv sync --locked`; `ruff check`; `ruff format --check`; `mypy` (strict, over src, tests, migrations and scripts); `alembic -x schema=clinic_test upgrade head`; `pytest -q` (unit + integration; `live` and `eval` markers excluded by default); `pip_audit` |
| `web` (ubuntu, 15 min, Node 24) | `npm ci`; `npm run lint`; `npx tsc --noEmit`; `npm run test` (Vitest); `npm run build` (with `API_PORT=8000`); `npm audit --omit=dev --audit-level=high` |

CI uses placeholder secrets and `DB_SSL=disable`; it never reaches Telegram or Gemini.

### B13.4 Backend toolchain (`apps/backend/pyproject.toml`)

Python ≥ 3.14, built with `uv_build`; console scripts `clinic-api` and `clinic-bot`. Exact versions are locked
in `uv.lock` (CI installs with `--locked`): alembic 1.20.1, argon2-cffi 25.1.0, asyncpg 0.32.0, fastapi
0.162.0, google-genai 2.34.0, phonenumbers 9.0.42, pydantic 2.14.2, pydantic-settings 2.16.2,
python-telegram-bot[job-queue] 22.8 (with APScheduler 3.11.3), sqlalchemy[asyncio] 2.1.6, structlog 26.1.0,
uvicorn 0.54.0; dev: httpx 0.28.1, mypy 2.4.1, pip-audit 2.10.1, pytest 9.2.0, pytest-asyncio 1.4.1.post1,
ruff 0.17.3. Ruff: line length 110, rule sets including security (`S`), async (`ASYNC`) and datetime (`DTZ`);
`TRY400` is disabled on purpose because tracebacks can carry personal data. Pytest treats warnings as errors.

## B14 Test architecture

| Level | Location | How it works |
|---|---|---|
| Backend unit | `apps/backend/tests/unit` | pure functions and components with fake clocks and a `ScriptedLLM` double; no database |
| Backend integration | `apps/backend/tests/integration` | real PostgreSQL schema `clinic_test` as `clinic_test_app`; every test starts from `TRUNCATE ... RESTART IDENTITY CASCADE` (run as the migrator) and a reset reference sequence; services get a pinned clock (mostly Monday 7 January 2030 08:00 IST); the staff API is driven in-process through `httpx.ASGITransport` |
| Schema tests | `test_schema.py`, `test_migrations.py` | RLS on all 15 tables, double-booking constraints, audit grants and trigger, role isolation, models equal to the migrated schema, migrations reversible |
| Agent evaluation | `test_agent_eval.py` (marker `eval`) | 38 scripted scenarios with the real Gemini model on a reseeded schema; a fallback reply counts as a failure (D-36); report written to `apps/backend/reports/` |
| Live smoke | marker `live` | real Gemini / booking journey with synthetic data |
| Dashboard unit/component | `apps/web/tests/unit` (Vitest) | B10 |
| Dashboard end-to-end | `apps/web/tests/e2e` (Playwright) | B10; fixture CLIs in `apps/backend/tests/e2e_support` create rows marked `Playwright ...` / `e2e_tmp_` and `cleanup.py` deletes only marked rows |

Integration, live and eval runs share `clinic_test`, so they must not run at the same time.

## B15 Catalogues

### B15.1 Audit actions (all `action` values written by the code)

| Action | Actor type | Written by |
|---|---|---|
| tool name (`list_doctors`, `check_availability`, `book_appointment`, `list_my_appointments`, `reschedule_appointment`, `cancel_appointment`, `get_clinic_info`, `handoff_to_staff`) or `unknown_tool` | agent | `agent/loop.py` |
| `appointment.book` | patient_button or staff | `services/booking.py:481` |
| `appointment.cancel`, `appointment.reschedule`, `appointment.patient_confirm` | patient_button | `services/booking.py` |
| `appointment.staff_cancel`, `appointment.attendance`, `appointment.clear_attention` | staff | `services/staff_ops.py` |
| `patient.register`, `patient.phone_conflict`, `patient.delete` | patient_button | `services/patients.py` |
| `patient.create` (walk-in) | staff | `services/staff_ops.py:354` |
| `ticket.resolve`, `alert.acknowledge` | staff | `services/staff_ops.py` |
| `handoff.request` | agent | `services/handoff.py:24` |
| `emergency.alert` | system | `services/alerts.py:39` |
| `doctor.create`, `doctor.update`, `doctor.schedule`, `doctor.leave`, `doctor.leave_delete` | staff | `services/admin.py` |
| `faq.save`, `faq.delete`, `settings.update` | staff | `services/admin.py` |
| `staff_user.create` | staff | `services/staff_auth.py:162` |
| `staff_user.update`, `staff_user.unlock` | staff | `services/admin.py` |
| `staff.login`, `staff.lockout`, `staff.logout` | staff | `services/staff_auth.py` |

### B15.2 Log events

Info: `http_request`, `agent_tool_call`, `bot_starting`, `bot_stopped`, `callback_expired_or_unknown`,
`callback_markup_not_removed`, `patient_data_deleted`, `rate_limited`, `registration_completed`,
`registration_contact_rejected`, `reminder_run`, `scheduler_heartbeat`, `typing_status_failed`.
Warning: `agent_budget_exhausted`, `agent_empty_reply`, `agent_tool_limit`, `db_tls_unverified`,
`emergency_redirected`, `grounding_failed`, `llm_empty_response`, `llm_unavailable`,
`login_failure_purge_failed`, `notification_retry`, `readiness_failed`, `reminder_delivery_failed`,
`reply_send_retry`.
Error: `audit_write_failed`, `conversation_failed`, `http_unhandled_error`, `notification_failed`,
`outbox_job_failed`, `reminder_failed`, `reminder_job_failed`, `telegram_handler_error`, `tool_failed`.

### B15.3 Constants that shape behaviour

| Constant | Value | Where |
|---|---|---|
| Settings cache TTL | 30 s | `services/clinic_settings.py:42` |
| Alternatives offered on SLOT_TAKEN | 3 | `services/booking.py:32` |
| Slots shown per availability answer | 5 | `agent/tools.py:211` |
| Max tool calls per turn | 5 | `agent/loop.py:59` |
| LLM temperature / max output tokens | 0.2 / 1024 | `agent/llm.py:158-159` |
| LLM retry on 500/502/503/504 | 1 retry, 0.5-1.0 s | `agent/llm.py:29-31` |
| Pending action TTL / token | 10 min / 12 chars | `agent/pending.py:15, 45` |
| Conversation memory | 10 exchanges, 2 h idle | `agent/memory.py` |
| Registration state idle TTL | 1 h | `conversation/registration.py:14` |
| Message length limit | 1,000 characters | `conversation/service.py:39` |
| Patient rate limit | 20 / 60 s, then 60 s mute | `agent/rate_limit.py:17-19` |
| Repeated tool failures before handoff button | 3 | `conversation/service.py:50` |
| Emergency alert de-duplication | 10 min | `services/alerts.py:12` |
| Reminder job / outbox job interval | 300 s / 60 s | `bot/telegram_app.py:161` |
| Reminder delivery retries | after 2, 4, 8 s | `services/reminders.py:37` |
| Outbox batch / lease / attempts / back-off | 20 / 5 min / 3 / 1 min then 5 min | `services/notifications.py:27-30` |
| Typing refresh / message split / send retry | 4 s / 4,096 chars / once after 1 s | `bot/telegram_app.py` |
| Login rate limit | 10 per minute per client | `api/app.py:38` |
| Readiness timeout | 5 s | `api/app.py:39` |
| Keep-alive | 65 s | `api/__main__.py:17` |
| Session lifetime / idle / lockout | 12 h / 60 min / 5 failures in 15 min, locked 15 min | `services/staff_auth.py:42-47` |

## B16 Known limitations of the current implementation

Found by reading the code; each is a fact about the build, not a plan.

| Area | Limitation | Where |
|---|---|---|
| Scaling | Conversation memory, pending confirmations, registration state, rate limits and per-user locks live in one bot process; a restart forgets them and several bot instances would not share them | `agent/memory.py`, `agent/pending.py`, `conversation/registration.py`, `agent/rate_limit.py` |
| Emergency detection | Keyword (whole-phrase) matching only; an LLM-based second check is noted as future scope | `agent/guardrails.py:1-4` |
| Grounding | Times written fully in words ("half past ten") are not detected | `agent/grounding.py:7-8` |
| Reminders | At most once: if the process stops between claiming and sending, that reminder stays `pending` and is never sent or flagged | `services/reminders.py:3-6` |
| Clinic notices | At least once: a crash after sending but before recording repeats the notice | `services/notifications.py:6-7` |
| 2-hour reminder | Has no buttons (only the 24-hour reminder offers Confirm, Reschedule, Cancel) | `services/reminders.py:70-74` |
| Leave removal | Deleting a leave day does not restore the bookings it cancelled | `services/admin.py:301-307` |
| Schedules | Overlapping blocks are prevented by the service only; there is no database constraint for them | `services/admin.py:107-120` |
| Staff passwords | The API lets an admin change their own password (only self-deactivation and self-demotion are refused); the dashboard hides the action on the admin's own row | `services/admin.py:508-511`, `web/features/admin/staff/staff-accounts.tsx:368` |
| Memory of failed turns | A turn that ends in a fallback, a limit or an ungrounded reply is not remembered, so the model does not see its own failed attempt | `agent/loop.py:100` |
| Settings changes | Reach each process within 30 s (cache), not immediately | `services/clinic_settings.py:42` |
| Deployment | Windows PowerShell scripts only; Telegram long polling only (no webhook); no container images | `scripts/*.ps1`, `bot/__main__.py:35` |
| TLS | Without `DB_SSL_ROOT_CERT` the database connection is encrypted but the certificate is not verified (a warning is logged; production refuses to start) | `db/session.py` |
| Relative CA path | `DB_SSL_ROOT_CERT` is validated as a file path relative to the process working directory, which is `apps/backend` under `start.ps1`; `check_env.py` resolves relative paths against the repository root instead. Not verified at run time | `config.py:34`, `scripts/start.ps1:108-109` |
| API docs | Swagger UI and OpenAPI JSON are served only when `ENV=development` | `api/app.py:128-131` |
| Seed data | The FAQ answer says the clinic is open until 7:00 PM, `staff_hours_text` says 6:00 PM, and one doctor's block ends at 19:00 | `apps/backend/scripts/seed.py` |
| Documentation drift | `.env.example` says `clinic_migrator` owns both schemas, but `bootstrap.sql` leaves the schemas with the owner (the migrator owns the tables); `eval_scenarios.py`'s docstring says 35 scenarios while it defines 38 | `.env.example:16`, `infrastructure/db/bootstrap.sql:22-23` |
