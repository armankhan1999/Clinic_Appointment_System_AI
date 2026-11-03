# M1 Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Execution note (2026-11-03):** the plan author executes this plan inline with TDD, because every task touches the shared core package and the author holds the full design context. Each task therefore lists its interfaces, the failing tests to write first (with their exact assertions), and the code that is easy to get wrong (DDL, privileges, driver settings). Routine code is written test-first during execution, not duplicated here. Review subagents check each milestone before it is closed.

**Goal:** a runnable Python backend that holds the complete database schema, seeds synthetic data, registers patients through Telegram with consent, and answers "which doctors do you have?" through a Gemini tool-calling loop that writes an audit row for every tool call.

**Architecture:** one uv project in `apps/backend` with the `clinic` package (layering from `docs/architecture/system-architecture.md`: `domain` is pure, `services` own all rules, adapters `bot` and `api` contain none). SQLAlchemy 2 async on asyncpg (D-25) through the Supabase session pooler; Alembic owns the schema; runtime schema chosen with `schema_translate_map`.

**Tech stack:** Python 3.14, uv, FastAPI, Pydantic 2, pydantic-settings, SQLAlchemy 2.1 (asyncio), asyncpg, Alembic, python-telegram-bot 22.8 [job-queue], google-genai 2.34, argon2-cffi, structlog, phonenumbers; pytest, pytest-asyncio, httpx, ruff, mypy, pip-audit.

## Global Constraints

- Stories in scope: E7-S1, E7-S2 (AC1, AC2; AC3 needs the API audit endpoint in M5), E1-S1, E1-S2, E1-S3, E2-S1, plus the schema part of E2-S4-AC2 and the seed (E7-S1-AC3).
- Decisions that bind every task: D-09 consent before the Share-phone button; D-10 safety-critical logic is code; D-16 no patient name, phone or Telegram ID is ever sent to the LLM; D-17 tests use schema `clinic_test` as role `clinic_test_app`; D-20 the app never connects as `postgres`; D-25 asyncpg.
- Timestamps are `timestamptz` in UTC. Clinic time zone comes from `clinic_settings.timezone` (seeded from `CLINIC_TIMEZONE`).
- No secret, chat text, patient name or phone in logs or audit rows (NFR-06, NFR-11, E7-S2-AC2).
- No hard-coded clinic data in application code: clinic name, phone, hours, emergency settings come from `clinic_settings`; seed data lives only in `apps/backend/scripts/seed.py`.
- Every migration has a working `downgrade()`.
- Lint `ruff check` + `ruff format --check`, types `mypy src`, tests `pytest` must be clean before a task is closed.
- Commands are run from `apps/backend` with `uv run …`. Integration tests need the repository `.env`.

## File structure

```
apps/backend/
  pyproject.toml, uv.lock, alembic.ini, README.md
  migrations/env.py, migrations/script.py.mako, migrations/versions/0001_baseline.py
  scripts/seed.py
  src/clinic/
    config.py                 Settings, DbTarget (role + schema + URL)
    observability.py          structlog JSON setup, request_id contextvar
    domain/results.py         ResultCode (StrEnum)
    domain/patients.py        normalise_name, normalise_phone, InvalidName, InvalidPhone
    domain/appointments.py    AppointmentStatus, can_transition (IMP-15)
    db/models.py              ORM models for every table (schema-less)
    db/session.py             make_engine(target), make_session_factory(engine)
    services/audit.py         AuditService.record(...)
    services/clinic_settings.py  ClinicSettingsService.get() -> ClinicSettingsView
    services/doctors.py       DoctorService.list_active(specialty) -> list[DoctorView]
    services/patients.py      PatientService (lookup, phone conflict check, register)
    services/tickets.py       TicketService.open_or_get(patient_id, reason)
    agent/llm.py              LLM protocol, LlmTurn, ToolCall, GeminiLLM, LlmUnavailable
    agent/tools.py            ToolContext, ToolSpec, ToolRegistry, list_doctors tool
    agent/loop.py             AgentLoop.run(...) -> AgentOutcome
    agent/memory.py           ConversationMemory (last 20 messages per user)
    agent/prompt.py           build_system_prompt(settings_view, today)
    conversation/replies.py   Reply, Button (transport-agnostic)
    conversation/registration.py  RegistrationFlow state machine (consent → phone → name)
    conversation/service.py   ConversationService.handle_text/handle_contact/handle_callback
    bot/telegram_app.py       PTB Application wiring (private chats only)
    bot/__main__.py           `uv run clinic-bot`
    api/app.py                FastAPI factory, request-id middleware, error envelope, /healthz, /readyz
    api/__main__.py           `uv run clinic-api` (binds 127.0.0.1:8000)
  tests/conftest.py, tests/unit/…, tests/integration/…
.github/workflows/ci.yml      backend job (lint, types, unit, integration on a Postgres service)
```

---

### Task 1: Backend scaffold, configuration and logging (E7-S1-AC2)

**Files:** create `apps/backend/pyproject.toml`, `src/clinic/__init__.py`, `src/clinic/config.py`, `src/clinic/observability.py`, `tests/unit/test_config.py`, `tests/unit/test_observability.py`.

**Interfaces (produced):**
- `class Settings(BaseSettings)`: fields `env: Literal["development","test","production"]`, `supabase_project_ref: str`, `db_host: str`, `db_port: int = 5432`, `db_name: str = "postgres"`, `db_migrator_password/db_app_password/db_test_app_password: SecretStr`, `db_schema: str = "clinic"`, `db_test_schema: str = "clinic_test"`, `telegram_bot_token: SecretStr`, `gemini_api_key: SecretStr`, `gemini_model: str`, `clinic_timezone: str` (validated with `zoneinfo`), `llm_timeout_seconds: float = 8.0`, `log_level: str = "INFO"`. Reads the repository-root `.env`; unknown keys (e.g. `DB_OWNER_PASSWORD`) are ignored and never loaded into a field.
- `get_settings() -> Settings` (cached).
- `@dataclass(frozen=True) class DbTarget: role: str; schema: str; password: SecretStr` with `url(settings) -> sqlalchemy.URL` (`postgresql+asyncpg`, user `role.<ref>`, query none; TLS via connect args) and classmethods `app(settings)`, `test(settings)`, `migrator(settings, schema)`.
- `configure_logging(level: str) -> None`, `request_id_var: ContextVar[str | None]`, `new_request_id() -> str`.

**Tests first:**
- `Settings` built from explicit kwargs/env: `repr(settings)` and `str(settings.gemini_api_key)` never contain the secret value.
- Missing `TELEGRAM_BOT_TOKEN` → `ValidationError`.
- `clinic_timezone="Mars/Olympus"` → `ValidationError`; `"Asia/Kolkata"` accepted.
- `DbTarget.app(s).url(s).username == "clinic_app.<ref>"`, driver `postgresql+asyncpg`, host/port/db from settings, and `render_as_string(hide_password=True)` hides the password.
- `DbTarget.migrator(s, "clinic_test").schema == "clinic_test"`; any other schema name than the two configured ones → `ValueError`.
- Logging: after `configure_logging`, a log call inside a bound request id emits one JSON line containing `request_id`, and a value passed as `phone=` is not special-cased (we never log it; the test asserts JSON shape only).

**Steps:** write tests → run (fail, module missing) → `uv init`/`uv add` the approved dependencies → implement → `uv run pytest tests/unit -q`, `uv run ruff check`, `uv run ruff format --check`, `uv run mypy src` → commit `feat(backend): scaffold, settings and structured logging`.

### Task 2: Domain rules (pure, no I/O)

**Files:** `src/clinic/domain/{__init__,results,patients,appointments}.py`, `tests/unit/test_domain_patients.py`, `tests/unit/test_domain_appointments.py`.

**Interfaces:** `class ResultCode(StrEnum)` with every code named in `docs/architecture/agent-design.md` and `api-and-auth.md` (OK, NO_MATCH, NO_SLOTS, INVALID_DATE, AMBIGUOUS_DATE, DOCTOR_NOT_WORKING, NOT_FOUND, PENDING_CONFIRMATION, SLOT_UNAVAILABLE, SLOT_TAKEN, LIMIT_REACHED, WITHIN_CUTOFF, ALREADY_CANCELLED, NONE, CREATED, ALREADY_OPEN, INVALID_ARGS, ERROR, VALIDATION_ERROR, FORBIDDEN, UNAUTHENTICATED, ACCOUNT_LOCKED, RATE_LIMITED). `normalise_name(raw: str) -> str` raises `InvalidName`; `normalise_phone(raw: str, default_region: str | None = None) -> str` returns E.164 or raises `InvalidPhone`; `first_name(full_name) -> str`. `AppointmentStatus(StrEnum)` booked/cancelled/completed/no_show; `can_transition(current, new, *, actor: Literal["patient","staff","admin","system"]) -> bool`.

**Tests first (E1-S2-AC3, IMP-15, GAP-22):**
- names: `"A"` → InvalidName; 61 letters → InvalidName; `"R2D2"` → InvalidName; `"  asha   rao "` → `"asha rao"`; `"Anne-Marie O'Neil"` accepted; `"---"` (no letter) → InvalidName; control characters → InvalidName; 2 and 60 chars accepted (boundaries).
- phone: Telegram sends `"919876543210"` (no plus) → `"+919876543210"`; `"+44 7700 900123"` → `"+447700900123"`; `"12"` → InvalidPhone; letters → InvalidPhone.
- transitions: booked→cancelled (patient, staff, system) ok; booked→completed/no_show only staff/admin; cancelled→anything False; completed↔no_show only admin; same-state False.

### Task 3: Database models, engine and baseline migration (E2-S4-AC2, E7-S2 storage, D-17, D-20)

**Files:** `src/clinic/db/{__init__,models,session}.py`, `alembic.ini`, `migrations/env.py`, `migrations/script.py.mako`, `migrations/versions/0001_baseline.py`, `tests/integration/conftest.py`, `tests/integration/test_schema.py`, `tests/integration/test_migrations.py`.

**Interfaces:** ORM classes `ClinicSettings, Doctor, DoctorSchedule, DoctorLeave, Patient, Appointment, Reminder, Notification, HandoffTicket, EmergencyAlert, ClinicInfo, StaffUser, StaffSession, AuditLog` mirroring `docs/architecture/database-design.md` exactly (tables carry no schema). `make_engine(target: DbTarget, settings) -> AsyncEngine` with `pool_pre_ping=True`, `pool_size=5`, `max_overflow=5`, `connect_args={"ssl": "require", "server_settings": {"application_name": "clinic-<role>"}}`, `execution_options={"schema_translate_map": {None: target.schema}}`. `make_session_factory(engine) -> async_sessionmaker[AsyncSession]` (`expire_on_commit=False`).

**Migration rules (the parts that are easy to get wrong):**
- `env.py` connects as `clinic_migrator`; the schema comes from `-x schema=clinic|clinic_test` (default `clinic`); it validates the name against the two configured schemas, runs `SET search_path TO <schema>` on the connection, uses `version_table_schema=<schema>` and puts `schema` and `app_role` (`clinic_app` for `clinic`, `clinic_test_app` for `clinic_test`) into `config.attributes` for the revision.
- `0001_baseline.upgrade()` creates, in order: `appointment_ref_seq`; function `format_appointment_ref(bigint)` (`'APT-' || lpad(n::text, greatest(6, length(n::text)), '0')`, `IMMUTABLE`, `SET search_path = ''`) so references keep growing past 999999 instead of truncating; all tables with CHECK constraints for every enum; `appointments.ref` default `format_appointment_ref(nextval('appointment_ref_seq'))`; `ux_appt_doctor_start_booked` partial unique index; exclusion constraint `ex_appt_no_overlap` `EXCLUDE USING gist (doctor_id WITH =, tstzrange(start_time, end_time) WITH &&) WHERE (status = 'booked')`; partial unique `(patient_id) WHERE status='open'` on `handoff_tickets`; UNIQUE `(appointment_id, type)` on `reminders`, `(appointment_id, kind)` on `notifications`; unique `lower(username)`; all indexes from the design doc; trigger function `reject_audit_change()` + `BEFORE UPDATE OR DELETE` trigger on `audit_log`; `ENABLE ROW LEVEL SECURITY` on every table with one policy `FOR ALL TO <app_role> USING (true) WITH CHECK (true)`; grants: `SELECT, INSERT, UPDATE, DELETE` on all tables except `audit_log` (`SELECT, INSERT` only), `USAGE, SELECT` on sequences, `EXECUTE` on `format_appointment_ref`, plus matching `ALTER DEFAULT PRIVILEGES FOR ROLE clinic_migrator IN SCHEMA <schema>` so later migrations inherit them (audit tables created later must revoke explicitly).
- `downgrade()` reverses everything, including the default privileges.

**Tests first (integration, against `clinic_test`):**
- `test_migrations.py`: as migrator, `downgrade base` → no tables in `clinic_test`; `upgrade head` → all 14 tables; `downgrade base` → `upgrade head` again succeeds (reversibility, Global Constraint).
- `test_schema.py` (connected as `clinic_test_app`): the partial unique index exists with predicate `status = 'booked'` (E2-S4-AC2, read from `pg_indexes`); two `booked` rows for the same doctor and start → `IntegrityError`; a `cancelled` duplicate is allowed; an overlapping 20-minute booking that starts 10 minutes earlier → `IntegrityError` (exclusion); `UPDATE audit_log` and `DELETE FROM audit_log` → permission error; `CREATE TABLE` in `clinic_test` → permission error; refs come out as `APT-000001`, `APT-000002`; `format_appointment_ref(1234567) = 'APT-1234567'`; RLS is enabled on all 14 tables (`pg_class.relrowsecurity`); `clinic_test_app` cannot see schema `clinic` (`has_schema_privilege` false).

### Task 4: Seed data (E7-S1-AC3, GAP-16, GAP-27, GAP-28)

**Files:** `apps/backend/scripts/seed.py`, `tests/integration/test_seed.py`.

**Behaviour:** `uv run python scripts/seed.py [--target dev|test]` connects as the app role of that target, refuses to run when `ENV=production`, and is idempotent (natural keys: doctor name, FAQ topic, synthetic phone). It writes: the single `clinic_settings` row (clinic name "Demo Family Clinic", synthetic address and phone, `timezone` from `CLINIC_TIMEZONE`, emergency number `112`, phrases from the source list: "chest pain", "can't breathe", "cannot breathe", "unconscious", "severe bleeding", "heart attack", "stroke", "suicide"; cut-off 120, window 30, max upcoming 3, max per doctor per day 1, morning end 12:00, afternoon end 17:00, staff hours "Mon–Sat 9:00 AM – 6:00 PM"); 3 doctors (General Physician, Paediatrician, Dermatologist) with weekly patterns including a lunch break modelled as two rows; FAQ entries for `timings`, `fees`, `address`, `parking`, `what_to_bring` with aliases; 8 synthetic patients with phones from the fictional UK range `+447700900xxx`, `registered_via='staff'`, `consent_source='staff_verbal'` and **no Telegram ID** (so no real person can ever be messaged); 2 weeks of synthetic appointments (past week completed/no_show, coming week booked) that respect schedules and the per-patient limits.

**Tests first:** after running the seed twice against `clinic_test`: exactly 1 settings row, 3 active doctors each with ≥ 1 schedule row, 5 FAQ topics, 8 patients all with `telegram_user_id IS NULL`, appointments within 7 days back/forward, no booked overlap; `ENV=production` → non-zero exit and nothing written.

### Task 5: Core services — settings, doctors, audit, patients, tickets (E2-S1, E7-S2-AC1/AC2, E1-S2, E1-S3)

**Files:** `src/clinic/services/{__init__,clinic_settings,doctors,audit,patients,tickets}.py`, `tests/integration/test_services_*.py`.

**Interfaces:**
- `ClinicSettingsView` (frozen dataclass of every settings column, `tz: ZoneInfo`); `ClinicSettingsService(session_factory).get() -> ClinicSettingsView`.
- `DoctorView(id, name, specialty, working_weekdays: tuple[int, ...])`; `DoctorService.list_active(specialty: str | None) -> list[DoctorView]` (case-insensitive substring on specialty; inactive excluded — E2-S1-AC2).
- `AuditService.record(session, *, actor_type, actor_id, action, args: Mapping[str, JSONValue], result: str, patient_id: UUID | None, latency_ms: int | None, request_id: str | None) -> None` — writes inside the caller's transaction; rejects keys named `text`, `message`, `name`, `phone`, `full_name` (defence for E7-S2-AC2 and NFR-06) with `ValueError`.
- `PatientService.get_by_telegram(telegram_user_id) -> PatientView | None`; `check_phone(phone_e164, telegram_user_id) -> PhoneCheck` (`AVAILABLE`, `WALK_IN_MATCH`, `LINKED_ELSEWHERE`, `ALREADY_YOURS`); `register_from_telegram(*, telegram_user_id, phone_e164, full_name, consented_at) -> RegistrationOutcome` (`REGISTERED`, `LINKED_WALK_IN`, `LINKED_ELSEWHERE`) in one transaction that re-checks the phone under `SELECT … FOR UPDATE`, writes `consent_at`/`consent_source='telegram'`, and audits `patient.register` with `actor_type='patient_button'` and args `{"outcome": …}` only.
- `TicketService.open_or_get(session, *, patient_id: UUID | None, reason) -> tuple[ResultCode, UUID]` (`CREATED` / `ALREADY_OPEN`, relying on the partial unique index under concurrency). Registration conflicts (E1-S2-AC4) for an unregistered sender cannot reference a patient row, so the conflict ticket is opened against the **existing** patient who owns the phone, reason `registration_conflict`.

**Tests first:** inactive doctor excluded; specialty filter "derma" finds Dermatologist; unknown specialty returns `[]` (tool maps to `NO_MATCH`); working weekdays derived from schedule rows; audit row has all E7-S2-AC1 fields and rejecting `{"text": …}`; registration happy path stores consent; walk-in with same phone is linked, not duplicated (IMP-14); phone linked to another Telegram ID → `LINKED_ELSEWHERE`, no write, ticket created once even if called twice; same Telegram user registering twice → existing patient returned.

### Task 6: Agent core — LLM adapter, tools, loop, memory, prompt (E2-S1, E1-S1-AC3, AGT-06, E7-S3-AC3, D-16)

**Files:** `src/clinic/agent/{__init__,llm,tools,loop,memory,prompt}.py`, `tests/unit/test_agent_loop.py`, `tests/unit/test_agent_tools_schema.py`, `tests/unit/test_prompt.py`, `tests/integration/test_tool_list_doctors.py`.

**Interfaces:**
- `ToolCall(id: str, name: str, args: dict[str, Any])`; `LlmTurn(text: str | None, tool_calls: list[ToolCall])`; `ChatMessage(role: Literal["user","model","tool"], text: str | None = None, tool_calls=…, tool_results=…)`.
- `class LLM(Protocol): async def generate(self, *, system: str, history: Sequence[ChatMessage], tools: Sequence[ToolSpec]) -> LlmTurn`; `class LlmUnavailable(Exception)`.
- `GeminiLLM(api_key: SecretStr, model: str, timeout_s: float)`: `client.aio.models.generate_content` with `GenerateContentConfig(system_instruction=…, tools=[Tool(function_declarations=[FunctionDeclaration(name, description, parameters_json_schema=Model.model_json_schema())])], automatic_function_calling=AutomaticFunctionCallingConfig(disable=True), temperature=0.2, max_output_tokens=512)`, wrapped in `asyncio.timeout`; any SDK or timeout error → `LlmUnavailable` (message scrubbed).
- `ToolContext(patient_id: UUID, request_id: str, session_factory, settings_view)`; `ToolSpec(name, description, args_model: type[BaseModel], executor: Callable[[ToolContext, BaseModel], Awaitable[ToolResult]], writes: bool)`; `ToolResult(code: ResultCode, data: dict[str, Any])`; `build_registry(services) -> ToolRegistry` with `list_doctors` only in M1 (`ListDoctorsArgs(specialty: str | None = Field(None, max_length=40))`, `extra="forbid"`).
- `AgentLoop(llm, registry, audit, max_tool_calls=5).run(ctx, memory, user_text) -> AgentOutcome(text: str, tool_calls_made: int, stopped: Literal["reply","limit","llm_error"])`: validates args with the Pydantic model (invalid → `INVALID_ARGS` result goes back to the LLM, tool not executed, audited); audits every executed call (tool name, validated args, result code, latency, request id, patient id); stops after 5 calls with a safe reply that offers staff help; never passes `patient_id` from the LLM (args models have no such field and `extra="forbid"`).
- `ConversationMemory(max_messages=20)`: per-user deque; `clear(user)`.
- `build_system_prompt(view: ClinicSettingsView, today: date) -> str` — contains clinic name, today in the clinic time zone, scope, no medical advice, tool-results-are-data rule; contains no patient data (D-16).

**Tests first (scripted LLM double implementing the `LLM` protocol — the external dependency, not the loop):** text-only turn → reply; `list_doctors` call → executor runs once, result fed back, final text returned, one audit row; invalid args (`specialty` 200 chars, or an extra `patient_id` field) → executor not run, `INVALID_ARGS` sent back, audited; 6 consecutive tool calls → stops at 5 with `stopped="limit"`; `LlmUnavailable` → `stopped="llm_error"`; system prompt contains clinic name and no digits of any patient phone; JSON schema of `ListDoctorsArgs` has `additionalProperties: false`. Integration: `list_doctors` executor against seeded `clinic_test` returns 3 doctors; with an inactive doctor, that doctor is absent; `"neurology"` → `NO_MATCH`.

### Task 7: Conversation service and registration flow (E1-S1, E1-S2, E1-S3, GAP-04, GAP-37)

**Files:** `src/clinic/conversation/{__init__,replies,registration,service}.py`, `tests/unit/test_registration_flow.py`, `tests/integration/test_conversation_service.py`.

**Interfaces:** `Button(text, callback_data: str | None = None, request_contact: bool = False)`; `Reply(text: str, inline_buttons: list[list[Button]] = [], contact_button: Button | None = None, remove_keyboard: bool = False)`. `ConversationService(…)` with `handle_text(user: IncomingUser, text) -> list[Reply]`, `handle_contact(user, contact_user_id: int | None, phone: str) -> list[Reply]`, `handle_callback(user, data: str) -> list[Reply]`, where `IncomingUser(telegram_user_id: int, first_name_hint: str | None)`.

**Behaviour:**
- Unregistered user, any message or `/start`: welcome with clinic name, "appointments only", "cannot give medical advice", "please don't share health details here" (D-16), then the consent text (stored: name, phone, appointments; why; how to delete via /deletemydata) with **I agree** / **No thanks** (E1-S3-AC1, D-09).
- **No thanks** → clinic phone shared, flow state discarded, nothing written (E1-S3-AC2).
- **I agree** → Share phone number button (`request_contact`) (E1-S1-AC1 button, E1-S2-AC1).
- Contact whose `user_id` is missing or ≠ sender → rejected, asked to share own number (E1-S2-AC2).
- Phone `LINKED_ELSEWHERE` → not linked; handoff offered with clinic phone and staff hours; conflict ticket opened (E1-S2-AC4).
- Then the name prompt; invalid name → re-ask with the rule (E1-S2-AC3); valid name → `register_from_telegram`, `consent_at` saved (E1-S3-AC3), keyboard removed, greeting by first name.
- Registered user: first message of a bot session greets by first name (E1-S1-AC2, GAP-37), then the agent answers. The LLM receives the text only, no name (D-16).
- `LlmUnavailable` or the 8 s budget passing → fallback reply with the clinic phone, returned well within 10 s (E1-S1-AC3).
- Callback data format `v1:<kind>:<token>` (≤ 64 bytes); unknown or expired → "This request has expired, please ask again" (GAP-17).

**Tests first:** each bullet above as a test; plus "registration state lives in memory only — no row exists until the name step completes" and "fallback reply is produced in < 10 s when the LLM double sleeps 30 s" (uses a real timeout with a 0.2 s budget injected for the test, asserting the budget path, and a separate assertion that the default budget is 8 s).

### Task 8: Telegram adapter, API health service and one-command starts (E7-S1-AC1)

**Files:** `src/clinic/bot/{__init__,telegram_app,__main__}.py`, `src/clinic/api/{__init__,app,errors,middleware,__main__}.py`, `tests/unit/test_api_health.py`, `tests/unit/test_bot_mapping.py`, `pyproject.toml` scripts `clinic-bot`, `clinic-api`, `clinic-seed`.

**Behaviour:** the bot ignores non-private chats; maps `Reply` → `ReplyKeyboardMarkup`(contact button, one-time) / `InlineKeyboardMarkup` / `ReplyKeyboardRemove`; answers callback queries; long polling (D-18) with `drop_pending_updates=False`; logs no message text. The API: `X-Request-ID` accepted when it matches `^[A-Za-z0-9-]{8,64}$` else generated, echoed in the response; error envelope `{"error": {"code","message","request_id"}}` for HTTPException, validation errors (`VALIDATION_ERROR`, 422) and unhandled errors (`ERROR`, 500, no internals); `/healthz` → `{"status":"ok"}`; `/readyz` → 200 when `select 1` succeeds else 503 `{"status":"unavailable"}`; Swagger only when `ENV=development`; `clinic-api` binds `127.0.0.1:8000`.

**Tests first:** health 200 with request id echoed; malformed request id replaced; readyz 503 with a failing engine double; unknown route → envelope with `NOT_FOUND`; bot mapping of each `Reply` shape to the right PTB markup; group-chat update ignored.

**Live checks (recorded in the test-execution tracker):** `uv run clinic-api` + `curl /healthz` and `/readyz`; `uv run clinic-bot` starts polling against the real bot (startup log line, then stopped). A full Telegram tap-through needs a human with the Telegram app and is marked "Not verified" until Arman runs it.

### Task 9: CI and documentation

**Files:** `.github/workflows/ci.yml`, `infrastructure/db/ci_roles.sql` (CI-only passwords set in plain SQL for the throwaway service container), `apps/backend/README.md`, root `README.md`, tracker updates.

**CI job:** Postgres 17 service container → run `bootstrap.sql` as superuser → `ci_roles.sql` → `uv sync --locked` → `ruff check`, `ruff format --check`, `mypy src` → `pytest -m "not live and not eval"` with `.env` built from CI env vars → `alembic` up/down/up → `pip-audit`. Not runnable locally (no Docker, no push); marked "Not verified" until a push runs it.

**Docs:** quick start (PowerShell), commands per process, test commands, the schema/role model, troubleshooting (pooler host, Windows notes).

---

## Self-review

- Spec coverage: E1-S1 (AC1 T7, AC2 T7, AC3 T6/T7), E1-S2 (AC1–AC4 T5/T7), E1-S3 (AC1–AC3 T7/T5), E2-S1 (AC1–AC3 T5/T6; AC3's "agent says so" is a prompt rule verified by the M6 eval suite), E7-S1 (AC1 bot/API in T8, dashboard in M5; AC2 T1 + existing `.gitignore`; AC3 T4), E7-S2 (AC1/AC2 T5/T6; AC3 in M5), E2-S4-AC2 (T3).
- Placeholder scan: done. Every task names its files, interfaces and tests.
- Type consistency: `ResultCode`, `ToolResult`, `ToolContext`, `Reply`, `Button` are defined once (T2, T6, T7) and reused by name.

## Later milestones (plans written when each starts)

M2 booking core (availability, date resolver, book/confirm with revalidation, 10-parallel concurrency test, emergency filter, grounding) · M3 manage (list/reschedule/cancel, medical refusal, relative dates) · M4 reminders, FAQ, handoff, rate/length limits · M5 staff API + Next.js dashboard · M6 eval suite, deletion, injection tests, attendance, metrics, packaging, final docs.
