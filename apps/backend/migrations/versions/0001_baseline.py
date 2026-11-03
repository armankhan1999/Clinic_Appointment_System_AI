"""Baseline schema: every table from docs/architecture/database-design.md.

Runs as clinic_migrator with search_path set to the target schema (see env.py), so object names
are unqualified. The app role (clinic_app or clinic_test_app) gets DML only; audit_log is
INSERT/SELECT only and protected by a trigger (E7-S2, D-20).

Revision ID: 0001
Revises:
Create Date: 2026-11-03
"""

import re
from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "staff_users", "staff_sessions", "clinic_settings", "doctors", "doctor_schedules", "doctor_leaves",
    "patients", "appointments", "reminders", "notifications", "handoff_tickets", "emergency_alerts",
    "clinic_info", "audit_log",
)  # fmt: skip
_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def _target() -> tuple[str, str]:
    config = op.get_context().config
    if config is None:
        raise RuntimeError("run migrations through the Alembic command line (env.py sets the target)")
    schema, app_role = config.attributes["schema"], config.attributes["app_role"]
    for name in (schema, app_role):
        if not _IDENTIFIER.match(name):
            raise ValueError(f"unsafe identifier {name!r}")
    return schema, app_role


DDL = """
CREATE SEQUENCE appointment_ref_seq AS bigint START WITH 1;

CREATE FUNCTION format_appointment_ref(n bigint) RETURNS text
    LANGUAGE sql IMMUTABLE STRICT SET search_path = ''
    AS $$ SELECT 'APT-' || lpad(n::text, greatest(6, length(n::text)), '0') $$;

CREATE TABLE staff_users (
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    username text NOT NULL,
    display_name text NOT NULL,
    password_hash text NOT NULL,
    role text NOT NULL,
    active boolean NOT NULL DEFAULT true,
    failed_attempts smallint NOT NULL DEFAULT 0,
    first_failed_at timestamptz,
    locked_until timestamptz,
    last_login_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_staff_users PRIMARY KEY (id),
    CONSTRAINT ck_staff_users_role CHECK (role IN ('receptionist', 'admin')),
    CONSTRAINT ck_staff_users_username CHECK (char_length(username) BETWEEN 3 AND 40),
    CONSTRAINT ck_staff_users_failed_attempts CHECK (failed_attempts >= 0)
);
CREATE UNIQUE INDEX ux_staff_users_username_lower ON staff_users (lower(username));

CREATE TABLE staff_sessions (
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    staff_user_id uuid NOT NULL,
    token_hash bytea NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    revoked_at timestamptz,
    CONSTRAINT pk_staff_sessions PRIMARY KEY (id),
    CONSTRAINT uq_staff_sessions_token_hash UNIQUE (token_hash),
    CONSTRAINT fk_staff_sessions_staff_user_id FOREIGN KEY (staff_user_id)
        REFERENCES staff_users (id) ON DELETE CASCADE
);
CREATE INDEX ix_staff_sessions_staff_user_id ON staff_sessions (staff_user_id);

CREATE TABLE clinic_settings (
    id smallint NOT NULL DEFAULT 1,
    clinic_name text NOT NULL,
    phone text NOT NULL,
    address text NOT NULL,
    staff_hours_text text NOT NULL,
    timezone text NOT NULL,
    emergency_number text NOT NULL,
    emergency_phrases text[] NOT NULL DEFAULT '{}'::text[],
    cutoff_minutes integer NOT NULL DEFAULT 120,
    booking_window_days integer NOT NULL DEFAULT 30,
    max_upcoming_per_patient integer NOT NULL DEFAULT 3,
    max_per_doctor_per_day integer NOT NULL DEFAULT 1,
    morning_end time NOT NULL DEFAULT '12:00',
    afternoon_end time NOT NULL DEFAULT '17:00',
    updated_by uuid,
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_clinic_settings PRIMARY KEY (id),
    CONSTRAINT ck_clinic_settings_single_row CHECK (id = 1),
    CONSTRAINT ck_clinic_settings_cutoff CHECK (cutoff_minutes BETWEEN 0 AND 10080),
    CONSTRAINT ck_clinic_settings_window CHECK (booking_window_days BETWEEN 1 AND 365),
    CONSTRAINT ck_clinic_settings_limits CHECK (
        max_upcoming_per_patient >= 1 AND max_per_doctor_per_day >= 1
    ),
    CONSTRAINT ck_clinic_settings_day_parts CHECK (afternoon_end > morning_end),
    CONSTRAINT fk_clinic_settings_updated_by FOREIGN KEY (updated_by) REFERENCES staff_users (id)
);

CREATE TABLE doctors (
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    name text NOT NULL,
    specialty text NOT NULL,
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_doctors PRIMARY KEY (id),
    CONSTRAINT ck_doctors_name CHECK (char_length(name) BETWEEN 2 AND 80),
    CONSTRAINT ck_doctors_specialty CHECK (char_length(specialty) BETWEEN 2 AND 80)
);
CREATE INDEX ix_doctors_active ON doctors (active);

CREATE TABLE doctor_schedules (
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    doctor_id uuid NOT NULL,
    weekday smallint NOT NULL,
    start_time time NOT NULL,
    end_time time NOT NULL,
    slot_minutes smallint NOT NULL DEFAULT 15,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_doctor_schedules PRIMARY KEY (id),
    CONSTRAINT ck_doctor_schedules_weekday CHECK (weekday BETWEEN 0 AND 6),
    CONSTRAINT ck_doctor_schedules_hours CHECK (end_time > start_time),
    CONSTRAINT ck_doctor_schedules_slot_minutes CHECK (slot_minutes BETWEEN 5 AND 120),
    CONSTRAINT fk_doctor_schedules_doctor_id FOREIGN KEY (doctor_id)
        REFERENCES doctors (id) ON DELETE RESTRICT
);
CREATE INDEX ix_doctor_schedules_doctor_id_weekday ON doctor_schedules (doctor_id, weekday);

CREATE TABLE doctor_leaves (
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    doctor_id uuid NOT NULL,
    leave_date date NOT NULL,
    reason text NOT NULL DEFAULT '',
    created_by uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_doctor_leaves PRIMARY KEY (id),
    CONSTRAINT uq_doctor_leaves_doctor_id_leave_date UNIQUE (doctor_id, leave_date),
    CONSTRAINT ck_doctor_leaves_reason CHECK (char_length(reason) <= 200),
    CONSTRAINT fk_doctor_leaves_doctor_id FOREIGN KEY (doctor_id) REFERENCES doctors (id) ON DELETE RESTRICT,
    CONSTRAINT fk_doctor_leaves_created_by FOREIGN KEY (created_by) REFERENCES staff_users (id)
);

CREATE TABLE patients (
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    telegram_user_id bigint,
    phone text,
    full_name text,
    consent_at timestamptz,
    consent_source text,
    registered_via text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz,
    CONSTRAINT pk_patients PRIMARY KEY (id),
    CONSTRAINT uq_patients_telegram_user_id UNIQUE (telegram_user_id),
    CONSTRAINT uq_patients_phone UNIQUE (phone),
    CONSTRAINT ck_patients_identity CHECK (
        deleted_at IS NOT NULL OR (phone IS NOT NULL AND full_name IS NOT NULL AND consent_at IS NOT NULL)
    ),
    CONSTRAINT ck_patients_full_name CHECK (
        full_name IS NULL OR (char_length(full_name) BETWEEN 2 AND 60 AND full_name !~ '[0-9]')
    ),
    CONSTRAINT ck_patients_phone CHECK (phone IS NULL OR phone ~ '^\\+[1-9][0-9]{6,14}$'),
    CONSTRAINT ck_patients_consent_source CHECK (consent_source IN ('telegram', 'staff_verbal')),
    CONSTRAINT ck_patients_registered_via CHECK (registered_via IN ('bot', 'staff'))
);

CREATE TABLE appointments (
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    ref text NOT NULL DEFAULT format_appointment_ref(nextval('appointment_ref_seq')),
    patient_id uuid NOT NULL,
    doctor_id uuid NOT NULL,
    start_time timestamptz NOT NULL,
    end_time timestamptz NOT NULL,
    status text NOT NULL DEFAULT 'booked',
    source text NOT NULL,
    rescheduled_from uuid,
    cancelled_at timestamptz,
    cancelled_by_kind text,
    cancel_reason text,
    patient_confirmed_at timestamptz,
    staff_attention_reason text,
    staff_attention_at timestamptz,
    created_by_staff_id uuid,
    attendance_marked_by uuid,
    attendance_marked_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_appointments PRIMARY KEY (id),
    CONSTRAINT uq_appointments_ref UNIQUE (ref),
    CONSTRAINT ck_appointments_times CHECK (end_time > start_time),
    CONSTRAINT ck_appointments_status CHECK (status IN ('booked', 'cancelled', 'completed', 'no_show')),
    CONSTRAINT ck_appointments_source CHECK (source IN ('bot', 'staff')),
    CONSTRAINT ck_appointments_cancelled_by_kind CHECK (cancelled_by_kind IN ('patient', 'staff', 'system')),
    CONSTRAINT ck_appointments_cancellation CHECK (
        status <> 'cancelled' OR (cancelled_at IS NOT NULL AND cancelled_by_kind IS NOT NULL)
    ),
    CONSTRAINT ck_appointments_cancel_reason CHECK (char_length(cancel_reason) <= 200),
    CONSTRAINT fk_appointments_patient_id FOREIGN KEY (patient_id)
        REFERENCES patients (id) ON DELETE RESTRICT,
    CONSTRAINT fk_appointments_doctor_id FOREIGN KEY (doctor_id) REFERENCES doctors (id) ON DELETE RESTRICT,
    CONSTRAINT fk_appointments_rescheduled_from FOREIGN KEY (rescheduled_from) REFERENCES appointments (id),
    CONSTRAINT fk_appointments_created_by_staff_id FOREIGN KEY (created_by_staff_id)
        REFERENCES staff_users (id),
    CONSTRAINT fk_appointments_attendance_marked_by FOREIGN KEY (attendance_marked_by)
        REFERENCES staff_users (id),
    -- REC-DB-01: no overlapping booked appointments per doctor, even after slot lengths change.
    CONSTRAINT ex_appt_no_overlap EXCLUDE USING gist (
        doctor_id WITH =, tstzrange(start_time, end_time) WITH &&
    ) WHERE (status = 'booked')
);
-- E2-S4-AC2: one booked appointment per doctor and start time.
CREATE UNIQUE INDEX ux_appt_doctor_start_booked ON appointments (doctor_id, start_time)
    WHERE status = 'booked';
CREATE INDEX ix_appointments_patient_id_status_start_time ON appointments (patient_id, status, start_time);
CREATE INDEX ix_appointments_booked_start_time ON appointments (start_time) WHERE status = 'booked';
CREATE INDEX ix_appointments_doctor_id_start_time ON appointments (doctor_id, start_time);

CREATE TABLE reminders (
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    appointment_id uuid NOT NULL,
    type text NOT NULL,
    status text NOT NULL DEFAULT 'pending',
    attempts smallint NOT NULL DEFAULT 0,
    last_error text,
    claimed_at timestamptz NOT NULL DEFAULT now(),
    sent_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_reminders PRIMARY KEY (id),
    CONSTRAINT uq_reminders_appointment_id_type UNIQUE (appointment_id, type),
    CONSTRAINT ck_reminders_type CHECK (type IN ('24h', '2h')),
    CONSTRAINT ck_reminders_status CHECK (status IN ('pending', 'sent', 'failed', 'skipped')),
    CONSTRAINT fk_reminders_appointment_id FOREIGN KEY (appointment_id)
        REFERENCES appointments (id) ON DELETE RESTRICT
);

CREATE TABLE notifications (
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    appointment_id uuid NOT NULL,
    patient_id uuid NOT NULL,
    kind text NOT NULL,
    reason text NOT NULL,
    status text NOT NULL DEFAULT 'pending',
    attempts smallint NOT NULL DEFAULT 0,
    next_attempt_at timestamptz NOT NULL DEFAULT now(),
    last_error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    sent_at timestamptz,
    CONSTRAINT pk_notifications PRIMARY KEY (id),
    CONSTRAINT uq_notifications_appointment_id_kind UNIQUE (appointment_id, kind),
    CONSTRAINT ck_notifications_kind CHECK (kind IN ('clinic_cancelled', 'doctor_leave')),
    CONSTRAINT ck_notifications_status CHECK (status IN ('pending', 'sent', 'failed')),
    CONSTRAINT fk_notifications_appointment_id FOREIGN KEY (appointment_id)
        REFERENCES appointments (id) ON DELETE RESTRICT,
    CONSTRAINT fk_notifications_patient_id FOREIGN KEY (patient_id)
        REFERENCES patients (id) ON DELETE RESTRICT
);
CREATE INDEX ix_notifications_pending_next_attempt_at ON notifications (next_attempt_at)
    WHERE status = 'pending';

CREATE TABLE handoff_tickets (
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    patient_id uuid NOT NULL,
    reason text NOT NULL,
    status text NOT NULL DEFAULT 'open',
    created_at timestamptz NOT NULL DEFAULT now(),
    resolved_by uuid,
    resolved_at timestamptz,
    CONSTRAINT pk_handoff_tickets PRIMARY KEY (id),
    CONSTRAINT ck_handoff_tickets_reason CHECK (
        reason IN (
            'patient_requested', 'agent_failed', 'registration_conflict', 'change_within_cutoff', 'other'
        )
    ),
    CONSTRAINT ck_handoff_tickets_status CHECK (status IN ('open', 'resolved')),
    CONSTRAINT ck_handoff_tickets_resolution CHECK (status = 'open' OR resolved_at IS NOT NULL),
    CONSTRAINT fk_handoff_tickets_patient_id FOREIGN KEY (patient_id)
        REFERENCES patients (id) ON DELETE RESTRICT,
    CONSTRAINT fk_handoff_tickets_resolved_by FOREIGN KEY (resolved_by) REFERENCES staff_users (id)
);
-- E5-S4-AC3: at most one open ticket per patient.
CREATE UNIQUE INDEX ux_handoff_tickets_open_per_patient ON handoff_tickets (patient_id) WHERE status = 'open';

CREATE TABLE emergency_alerts (
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    patient_id uuid,
    telegram_user_id bigint,
    created_at timestamptz NOT NULL DEFAULT now(),
    acknowledged_by uuid,
    acknowledged_at timestamptz,
    CONSTRAINT pk_emergency_alerts PRIMARY KEY (id),
    CONSTRAINT ck_emergency_alerts_sender CHECK (patient_id IS NOT NULL OR telegram_user_id IS NOT NULL),
    CONSTRAINT fk_emergency_alerts_patient_id FOREIGN KEY (patient_id)
        REFERENCES patients (id) ON DELETE RESTRICT,
    CONSTRAINT fk_emergency_alerts_acknowledged_by FOREIGN KEY (acknowledged_by) REFERENCES staff_users (id)
);
CREATE INDEX ix_emergency_alerts_unacknowledged ON emergency_alerts (created_at)
    WHERE acknowledged_at IS NULL;

CREATE TABLE clinic_info (
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    topic text NOT NULL,
    aliases text[] NOT NULL DEFAULT '{}'::text[],
    answer text NOT NULL,
    updated_by uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_clinic_info PRIMARY KEY (id),
    CONSTRAINT uq_clinic_info_topic UNIQUE (topic),
    CONSTRAINT ck_clinic_info_topic CHECK (topic ~ '^[a-z0-9_]{1,40}$'),
    CONSTRAINT ck_clinic_info_answer CHECK (char_length(answer) BETWEEN 1 AND 2000),
    CONSTRAINT fk_clinic_info_updated_by FOREIGN KEY (updated_by) REFERENCES staff_users (id)
);

CREATE TABLE audit_log (
    id bigint GENERATED ALWAYS AS IDENTITY,
    ts timestamptz NOT NULL DEFAULT now(),
    actor_type text NOT NULL,
    actor_id text,
    patient_id uuid,
    action text NOT NULL,
    args_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    result text NOT NULL,
    latency_ms integer,
    request_id text,
    CONSTRAINT pk_audit_log PRIMARY KEY (id),
    CONSTRAINT ck_audit_log_actor_type CHECK (actor_type IN ('agent', 'staff', 'system', 'patient_button'))
);
CREATE INDEX ix_audit_log_ts ON audit_log (ts DESC);
CREATE INDEX ix_audit_log_patient_id_ts ON audit_log (patient_id, ts DESC);

CREATE FUNCTION reject_audit_change() RETURNS trigger
    LANGUAGE plpgsql SET search_path = ''
    AS $$ BEGIN RAISE EXCEPTION 'audit_log is append-only' USING ERRCODE = 'insufficient_privilege'; END $$;
CREATE TRIGGER audit_log_append_only BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION reject_audit_change();
"""


def upgrade() -> None:
    schema, app_role = _target()
    # Grants for every table this role creates from now on, including in later migrations.
    op.execute(
        f"ALTER DEFAULT PRIVILEGES FOR ROLE clinic_migrator IN SCHEMA {schema} "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {app_role}"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES FOR ROLE clinic_migrator IN SCHEMA {schema} "
        f"GRANT USAGE, SELECT ON SEQUENCES TO {app_role}"
    )
    # asyncpg runs one command per prepared statement. Statements here end with ';' at end of line;
    # the semicolons inside the $$ function bodies are mid-line.
    for statement in DDL.split(";\n"):
        if statement.strip():
            op.execute(statement)
    op.execute(f"REVOKE UPDATE, DELETE ON audit_log FROM {app_role}")
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY app_access ON {table} FOR ALL TO {app_role} USING (true) WITH CHECK (true)"
        )


def downgrade() -> None:
    schema, app_role = _target()
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE {table}")
    op.execute("DROP FUNCTION reject_audit_change()")
    op.execute("DROP FUNCTION format_appointment_ref(bigint)")
    op.execute("DROP SEQUENCE appointment_ref_seq")
    # Identifiers cannot be bound as parameters; both passed the _IDENTIFIER check in _target().
    op.execute(
        f"ALTER DEFAULT PRIVILEGES FOR ROLE clinic_migrator IN SCHEMA {schema} "  # noqa: S608
        f"REVOKE USAGE, SELECT ON SEQUENCES FROM {app_role}"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES FOR ROLE clinic_migrator IN SCHEMA {schema} "
        f"REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM {app_role}"
    )
