# Database Design

Engine: PostgreSQL on hosted Supabase (D-02). Migrations: **Alembic is the single source of truth** (no parallel `supabase/migrations`). All timestamps are `timestamptz` stored in UTC; local clinic time (settings `timezone`) is used only for slot generation and display. All tables live in schema `clinic`.

Sources: DM-00..11 (§3.6), ACs cited per rule, IMP-* (derived, see inventory §14). Columns marked **(IMP)** are not in the source data model and are added to satisfy a cited AC.

## ERD

```mermaid
erDiagram
    clinic_settings ||--o{ staff_users : "updated_by"
    patients ||--o{ appointments : books
    doctors ||--o{ appointments : "is booked for"
    doctors ||--o{ doctor_schedules : works
    doctors ||--o{ doctor_leaves : takes
    appointments ||--o{ reminders : "has"
    appointments ||--o{ notifications : "triggers"
    appointments ||--o| appointments : "rescheduled_from"
    patients ||--o{ handoff_tickets : raises
    patients ||--o{ emergency_alerts : triggers
    staff_users ||--o{ staff_sessions : has
    staff_users ||--o{ handoff_tickets : resolves
    staff_users ||--o{ clinic_info : edits
    staff_users ||--o{ doctor_leaves : creates

    patients { uuid id PK; bigint telegram_user_id UK "nullable"; text phone UK "nullable, E.164"; text full_name; timestamptz consent_at; text consent_source; timestamptz deleted_at }
    doctors { uuid id PK; text name; text specialty; bool active }
    doctor_schedules { uuid id PK; uuid doctor_id FK; smallint weekday; time start_time; time end_time; smallint slot_minutes }
    doctor_leaves { uuid id PK; uuid doctor_id FK; date leave_date; text reason }
    appointments { uuid id PK; text ref UK; uuid patient_id FK; uuid doctor_id FK; timestamptz start_time; timestamptz end_time; text status; text source; uuid rescheduled_from FK; timestamptz patient_confirmed_at; text staff_attention_reason }
    reminders { uuid id PK; uuid appointment_id FK; text type; text status; smallint attempts; timestamptz sent_at }
    notifications { uuid id PK; uuid appointment_id FK; text kind; text status; smallint attempts }
    handoff_tickets { uuid id PK; uuid patient_id FK; text reason; text status; uuid resolved_by FK; timestamptz resolved_at }
    emergency_alerts { uuid id PK; uuid patient_id FK; bigint telegram_user_id; uuid acknowledged_by FK }
    clinic_info { uuid id PK; text topic UK; text answer; uuid updated_by FK }
    staff_users { uuid id PK; text username UK; text password_hash; text role; smallint failed_attempts; timestamptz first_failed_at; timestamptz locked_until }
    staff_sessions { uuid id PK; uuid staff_user_id FK; bytea token_hash UK; timestamptz expires_at }
    audit_log { bigint id PK; timestamptz ts; text actor_type; text actor_id; uuid patient_id; text action; jsonb args_json; text result; int latency_ms; text request_id }
    clinic_settings { smallint id PK "always 1" }
```

## Entities

Enums are Postgres `CHECK` constraints on `text` columns rather than native enum types: they are easier to evolve in reversible migrations.

### patients — DM-01, E1, IMP-14
| Column | Type | Rules |
|---|---|---|
| id | uuid PK | `gen_random_uuid()` |
| telegram_user_id | bigint NULL | UNIQUE (DM-01). NULL for walk-in patients and after deletion |
| phone | text NULL | UNIQUE (DM-01); normalised E.164 |
| full_name | text NULL | 2–60 chars, no digits (E1-S2-AC3), enforced in service and by CHECK |
| consent_at | timestamptz NULL | Set when registration completes (E1-S3-AC3) |
| consent_source | text NULL | `telegram` \| `staff_verbal` (GAP-10) |
| registered_via | text | `bot` \| `staff` |
| created_at, updated_at | timestamptz | |
| deleted_at | timestamptz NULL | E1-S4. Deletion sets `full_name='Deleted patient'`, `phone=NULL`, `telegram_user_id=NULL` (GAP-25) |

CHECK: `deleted_at IS NOT NULL OR (phone IS NOT NULL AND full_name IS NOT NULL AND consent_at IS NOT NULL)`. Only name, phone, Telegram ID and appointments are stored, with no health fields (NFR-06).

### doctors — DM-02, IMP-01
`id`, `name`, `specialty`, `active bool default true`, timestamps. Index `(active)`. Inactive doctors never appear in `list_doctors` (E2-S1-AC2) or availability.

### doctor_schedules — DM-03, E6-S3, GAP-09
`id`, `doctor_id FK ON DELETE RESTRICT`, `weekday smallint CHECK 0..6` (0 = Monday), `start_time time`, `end_time time`, `slot_minutes smallint default 15 CHECK 5..120`. CHECK `end_time > start_time` (E6-S3-AC2). Breaks are modelled as several non-overlapping rows for one weekday. Overlap is rejected by the service, which serialises edits per doctor with `SELECT … FOR UPDATE` on the doctor row. Index `(doctor_id, weekday)`.

### doctor_leaves — DM-04
`id`, `doctor_id FK`, `leave_date date`, `reason text`, `created_by FK staff_users`, `created_at`. UNIQUE `(doctor_id, leave_date)`. Full-day leave only, as in the source (E2-S4-AC3).

### appointments — DM-05, E2, E3, E4, E6
| Column | Type | Rules |
|---|---|---|
| id | uuid PK | |
| ref | text UNIQUE | `APT-` + 6-digit zero-padded value from sequence `appointment_ref_seq` (IMP-10, E2-S3-AC2) |
| patient_id | uuid FK | Every patient-facing query filters on it (E3-S1-AC3) |
| doctor_id | uuid FK | |
| start_time, end_time | timestamptz | CHECK `end_time > start_time`; `end_time` stored so overlaps can be checked when slot length changes |
| status | text | `booked` \| `cancelled` \| `completed` \| `no_show` (DM-05); transitions enforced in the domain layer (IMP-15) |
| source | text | `bot` \| `staff` (DM-05, E6-S4-AC1) |
| rescheduled_from | uuid NULL FK → appointments | E3-S2-AC2 |
| cancelled_at, cancelled_by_kind, cancel_reason | NULL | `patient` \| `staff` \| `system`; reason shown to the patient in E4-S4 |
| patient_confirmed_at | timestamptz NULL | **(IMP-08)** E4-S3-AC1 |
| staff_attention_reason, staff_attention_at | NULL | **(IMP-09)** E4-S4-AC2: set when a notification or reminder fails after retries |
| created_by_staff_id, attendance_marked_by, attendance_marked_at | NULL | Staff provenance (E6-S4, E6-S5) |
| created_at, updated_at | timestamptz | |

Double-booking defences (BR-03, E2-S4):
1. **Required by source (E2-S4-AC2):** `CREATE UNIQUE INDEX ux_appt_doctor_start_booked ON appointments (doctor_id, start_time) WHERE status = 'booked'`.
2. **Recommended addition (REC-DB-01):** `EXCLUDE USING gist (doctor_id WITH =, tstzrange(start_time, end_time) WITH &&) WHERE (status = 'booked')`. This needs `btree_gist`. It stops overlapping bookings after an admin changes slot length (for example a 15-minute slot at 10:00 and a 20-minute slot at 09:50). It depends on `btree_gist` being available on Supabase, which is still being verified.
3. Both are violated inside the booking transaction, and the violation maps to `SLOT_TAKEN`.

Other indexes: `(patient_id, status, start_time)` for own-appointment lists and limits; partial `(start_time) WHERE status = 'booked'` for the reminder scan; `(doctor_id, start_time)` for the daily schedule.

### reminders — DM-06, E4-S1, E4-S2
`id`, `appointment_id FK`, `type` (`24h` \| `2h`), `status` (`pending` \| `sent` \| `failed` \| `skipped`), `attempts smallint`, `last_error text` (sanitised), `claimed_at`, `sent_at`, `created_at`. **UNIQUE `(appointment_id, type)`** (DM-06, E4-S1-AC3): a reminder is claimed by `INSERT … ON CONFLICT DO NOTHING RETURNING id`, and only the claimer sends it.

### notifications — outbox for clinic-side changes, E4-S4 (IMP)
`id`, `appointment_id FK`, `patient_id FK`, `kind` (`clinic_cancelled` \| `doctor_leave`), `reason text`, `status` (`pending` \| `sent` \| `failed`), `attempts`, `next_attempt_at`, `last_error`, `created_at`, `sent_at`. UNIQUE `(appointment_id, kind)`. The API writes rows in the same transaction as the cancellation or leave; the worker sends them. The API therefore never holds the Telegram token, and a crash cannot lose a notice.

### handoff_tickets — DM-07, E5-S4, IMP-07
`id`, `patient_id FK`, `reason` (`patient_requested` \| `agent_failed` \| `registration_conflict` \| `change_within_cutoff` \| `other`), `status` (`open` \| `resolved`), `created_at`, `resolved_by FK staff_users`, `resolved_at`. **Partial UNIQUE `(patient_id) WHERE status = 'open'`** enforces E5-S4-AC3 (no duplicate open ticket) at database level. `reason` is an enum, not LLM free text, so no health details can land here (NFR-06).

### emergency_alerts — IMP-06, E5-S3-AC3
`id`, `patient_id FK NULL`, `telegram_user_id bigint NULL` (for unregistered senders), `created_at`, `acknowledged_by FK NULL`, `acknowledged_at NULL`. **No message text is stored.** The dashboard shows name and phone through the patient join. Repeat alerts from one sender within 10 minutes are de-duplicated.

### clinic_info — DM-08, E5-S1, IMP-02
`id`, `topic text UNIQUE` (slug, e.g. `timings`, `fees`, `address`, `parking`, `what_to_bring`), `aliases text[]`, `answer text`, `updated_by FK`, `updated_at`. Edited by admin only.

### staff_users — DM-09, E6-S1, IMP-04
`id`, `username` (UNIQUE on `lower(username)`), `display_name`, `password_hash` (argon2id), `role` (`receptionist` \| `admin`), `active`, `failed_attempts`, `first_failed_at` (GAP-23), `locked_until`, `last_login_at`, timestamps.

### staff_sessions — supports E6-S1
`id`, `staff_user_id FK`, `token_hash bytea UNIQUE` (SHA-256 of a 256-bit random token; the raw token exists only in the HttpOnly cookie), `created_at`, `expires_at`, `last_seen_at`, `revoked_at`. Server-side sessions make logout and role changes take effect immediately.

### audit_log — DM-10, E7-S2, FR-10
`id bigserial`, `ts`, `actor_type` (`agent` \| `staff` \| `system` \| `patient_button`), `actor_id text`, `patient_id uuid NULL`, `action text` (tool name, or a staff action such as `appointment.cancel`), `args_json jsonb` (validated arguments only, no chat text: E7-S2-AC2), `result text` (result code), `latency_ms int`, `request_id text`. **Append-only:** the app role is granted only INSERT and SELECT, and a trigger rejects UPDATE and DELETE. Indexes `(ts DESC)`, `(patient_id, ts DESC)`.

### clinic_settings — IMP-05
Single row (`id smallint PK CHECK (id = 1)`): `clinic_name`, `phone`, `address`, `staff_hours_text`, `timezone` (IANA, validated), `emergency_number`, `emergency_phrases text[]`, `cutoff_minutes` (120), `booking_window_days` (30), `max_upcoming_per_patient` (3), `max_per_doctor_per_day` (1), `morning_end` (12:00), `afternoon_end` (17:00), `updated_by`, `updated_at`. Seeded from `.env` defaults; admin-editable.

## Access control at the database layer

- Three login roles (D-20), created by `infrastructure/db/bootstrap.sql`. None has superuser, CREATEDB, CREATEROLE or BYPASSRLS:
  - `clinic_migrator` has USAGE + CREATE on both schemas, runs Alembic and owns the tables.
  - `clinic_app` (dev runtime) and `clinic_test_app` (tests) have USAGE on their own schema only; table DML is granted by the baseline migration through `ALTER DEFAULT PRIVILEGES`; `audit_log` is INSERT/SELECT only.
  - `postgres` owns the schemas, so a rollback can drop them, and is not used at runtime.
- Verified 2026-11-02 by query through the MCP: Postgres 17.11; `postgres` is not superuser but has BYPASSRLS and CREATEROLE; `btree_gist` 1.7 is available.
- Schema `clinic` is **not** exposed through Supabase's Data API, so the anon and authenticated keys cannot reach it.
- RLS is enabled on every table, with policies granting access only to `clinic_app`. This is defence in depth: if the schema is ever exposed, other roles see nothing. Patient isolation is enforced in the service layer (every patient query is scoped to the session's patient ID) and tested (E3-S1-AC3, E7-S4-AC1). Postgres RLS is not used for per-patient isolation, because patients never connect to the database.
- Verified 2026-11-02 (supabase.com/docs/guides/database/postgres/roles, /hardening-data-api): custom LOGIN roles can be created on hosted projects, and the owner role `postgres` has BYPASSRLS. That is why the app must **not** connect as `postgres`. The Data API exposes `public` by default and can be switched off, so the setup guide turns it off.
- `btree_gist` **is available** on this project (version 1.7, verified 2026-11-02). The bootstrap installs it into schema `extensions`, so REC-DB-01 (the exclusion constraint) goes ahead.
- Backups: the Supabase Free plan has **no automatic backups** (supabase.com/pricing). The runbook documents `pg_dump` export and restore.

## Migration and data safety

- Every Alembic revision has a working `downgrade()`; CI runs `upgrade head → downgrade base → upgrade head` against an empty Postgres.
- The seed (`scripts/seed`) is separate from migrations and runs only against dev and test databases. It creates 3 doctors, weekly schedules, FAQ entries, synthetic patients and 2 weeks of synthetic appointments (E7-S1-AC3, GAP-16).
- Tests run in schema `clinic_test` as role `clinic_test_app`, which has no rights on `clinic` (D-17). Table definitions carry no hard-coded schema; the schema is mapped at runtime with SQLAlchemy's `schema_translate_map`, so one model set serves both schemas.

## Implementation notes (M1, verified 2026-11-03)

- Baseline revision `apps/backend/migrations/versions/0001_baseline.py` applied to `clinic` and `clinic_test`; `alembic current` → `0001 (head)`. Up/down/up is covered by `tests/integration/test_migrations.py`.
- `appointments.ref` uses `format_appointment_ref(nextval('appointment_ref_seq'))`, which pads to 6 digits and keeps growing (`APT-1234567`) instead of truncating.
- Supabase security advisor after the migration: 0 lints. Performance advisor: INFO only. "Unused index" is expected on an empty schema. "Unindexed foreign keys" lists the staff provenance columns (`updated_by`, `created_by`, `resolved_by`, `acknowledged_by`, `attendance_marked_by`, `created_by_staff_id`), `appointments.rescheduled_from`, `emergency_alerts.patient_id` and `notifications.patient_id`. Those indexes only speed up deletes or updates of the referenced row. Staff users are deactivated, never deleted; patients are anonymised, never deleted (E1-S4). They are therefore not added. Revisit if a query starts filtering on one of these columns.
- Driver: asyncpg (D-25). Raw SQL text is not affected by `schema_translate_map`, so application code uses SQLAlchemy constructs; tests that need raw SQL qualify the schema explicitly.
