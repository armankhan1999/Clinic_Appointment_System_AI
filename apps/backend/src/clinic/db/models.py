"""ORM models mirroring docs/architecture/database-design.md.

The Alembic migrations are the source of truth for the schema, including CHECK constraints,
the exclusion constraint, row-level security, grants and the audit trigger. These models carry
no schema name; the runtime schema is chosen with `schema_translate_map` (D-17).
`tests/integration/test_schema.py::test_models_match_the_migrated_schema` keeps both in step.
"""

import uuid
from datetime import date, datetime, time
from typing import Any, ClassVar

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    SmallInteger,
    Text,
    Time,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s",
    "pk": "pk_%(table_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map: ClassVar[dict[Any, Any]] = {
        str: Text(),
        datetime: DateTime(timezone=True),
        uuid.UUID: Uuid(),
        dict[str, Any]: JSONB(),
        list[str]: ARRAY(Text()),
        bytes: LargeBinary(),
    }


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(primary_key=True, default=uuid.uuid7, server_default=text("gen_random_uuid()"))


def _created_at() -> Mapped[datetime]:
    return mapped_column(server_default=func.now())


def _updated_at() -> Mapped[datetime]:
    return mapped_column(server_default=func.now(), onupdate=func.now())


class StaffUser(Base):
    __tablename__ = "staff_users"
    __table_args__ = (Index("ux_staff_users_username_lower", func.lower(text("username")), unique=True),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    username: Mapped[str]
    display_name: Mapped[str]
    password_hash: Mapped[str]
    role: Mapped[str]
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    failed_attempts: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    first_failed_at: Mapped[datetime | None]
    locked_until: Mapped[datetime | None]
    last_login_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class StaffSession(Base):
    __tablename__ = "staff_sessions"
    __table_args__ = (Index("ix_staff_sessions_staff_user_id", "staff_user_id"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    staff_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("staff_users.id", ondelete="CASCADE"))
    token_hash: Mapped[bytes] = mapped_column(unique=True)
    created_at: Mapped[datetime] = _created_at()
    expires_at: Mapped[datetime]
    last_seen_at: Mapped[datetime] = mapped_column(server_default=func.now())
    revoked_at: Mapped[datetime | None]


class ClinicSettings(Base):
    __tablename__ = "clinic_settings"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, server_default=text("1"))
    clinic_name: Mapped[str]
    phone: Mapped[str]
    address: Mapped[str]
    staff_hours_text: Mapped[str]
    timezone: Mapped[str]
    emergency_number: Mapped[str]
    emergency_phrases: Mapped[list[str]] = mapped_column(server_default=text("'{}'::text[]"))
    cutoff_minutes: Mapped[int] = mapped_column(Integer, server_default=text("120"))
    booking_window_days: Mapped[int] = mapped_column(Integer, server_default=text("30"))
    max_upcoming_per_patient: Mapped[int] = mapped_column(Integer, server_default=text("3"))
    max_per_doctor_per_day: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    morning_end: Mapped[time] = mapped_column(Time, server_default=text("'12:00'"))
    afternoon_end: Mapped[time] = mapped_column(Time, server_default=text("'17:00'"))
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("staff_users.id"))
    updated_at: Mapped[datetime] = _updated_at()


class Doctor(Base):
    __tablename__ = "doctors"
    __table_args__ = (Index("ix_doctors_active", "active"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str]
    specialty: Mapped[str]
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class DoctorSchedule(Base):
    __tablename__ = "doctor_schedules"
    __table_args__ = (Index("ix_doctor_schedules_doctor_id_weekday", "doctor_id", "weekday"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    doctor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("doctors.id", ondelete="RESTRICT"))
    weekday: Mapped[int] = mapped_column(SmallInteger)
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    slot_minutes: Mapped[int] = mapped_column(SmallInteger, server_default=text("15"))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class DoctorLeave(Base):
    __tablename__ = "doctor_leaves"
    __table_args__ = (UniqueConstraint("doctor_id", "leave_date"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    doctor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("doctors.id", ondelete="RESTRICT"))
    leave_date: Mapped[date] = mapped_column(Date)
    reason: Mapped[str] = mapped_column(server_default=text("''"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("staff_users.id"))
    created_at: Mapped[datetime] = _created_at()


class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[uuid.UUID] = _uuid_pk()
    telegram_user_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    phone: Mapped[str | None] = mapped_column(unique=True)
    full_name: Mapped[str | None]
    consent_at: Mapped[datetime | None]
    consent_source: Mapped[str | None]
    registered_via: Mapped[str]
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()
    deleted_at: Mapped[datetime | None]


class Appointment(Base):
    __tablename__ = "appointments"
    __table_args__ = (
        Index(
            "ux_appt_doctor_start_booked",
            "doctor_id",
            "start_time",
            unique=True,
            postgresql_where=text("status = 'booked'"),
        ),
        Index("ix_appointments_patient_id_status_start_time", "patient_id", "status", "start_time"),
        Index("ix_appointments_booked_start_time", "start_time", postgresql_where=text("status = 'booked'")),
        Index("ix_appointments_doctor_id_start_time", "doctor_id", "start_time"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    ref: Mapped[str] = mapped_column(
        unique=True, server_default=text("format_appointment_ref(nextval('appointment_ref_seq'))")
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id", ondelete="RESTRICT"))
    doctor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("doctors.id", ondelete="RESTRICT"))
    start_time: Mapped[datetime]
    end_time: Mapped[datetime]
    status: Mapped[str] = mapped_column(server_default=text("'booked'"))
    source: Mapped[str]
    rescheduled_from: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("appointments.id"))
    cancelled_at: Mapped[datetime | None]
    cancelled_by_kind: Mapped[str | None]
    cancel_reason: Mapped[str | None]
    patient_confirmed_at: Mapped[datetime | None]
    staff_attention_reason: Mapped[str | None]
    staff_attention_at: Mapped[datetime | None]
    created_by_staff_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("staff_users.id"))
    attendance_marked_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("staff_users.id"))
    attendance_marked_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class Reminder(Base):
    __tablename__ = "reminders"
    __table_args__ = (UniqueConstraint("appointment_id", "type"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    appointment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("appointments.id", ondelete="RESTRICT"))
    type: Mapped[str]
    status: Mapped[str] = mapped_column(server_default=text("'pending'"))
    attempts: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    last_error: Mapped[str | None]
    claimed_at: Mapped[datetime] = mapped_column(server_default=func.now())
    sent_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = _created_at()


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("appointment_id", "kind"),
        Index(
            "ix_notifications_pending_next_attempt_at",
            "next_attempt_at",
            postgresql_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    appointment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("appointments.id", ondelete="RESTRICT"))
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id", ondelete="RESTRICT"))
    kind: Mapped[str]
    reason: Mapped[str]
    status: Mapped[str] = mapped_column(server_default=text("'pending'"))
    attempts: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    next_attempt_at: Mapped[datetime] = mapped_column(server_default=func.now())
    last_error: Mapped[str | None]
    created_at: Mapped[datetime] = _created_at()
    sent_at: Mapped[datetime | None]


class HandoffTicket(Base):
    __tablename__ = "handoff_tickets"
    __table_args__ = (
        Index(
            "ux_handoff_tickets_open_per_patient",
            "patient_id",
            unique=True,
            postgresql_where=text("status = 'open'"),
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id", ondelete="RESTRICT"))
    reason: Mapped[str]
    status: Mapped[str] = mapped_column(server_default=text("'open'"))
    created_at: Mapped[datetime] = _created_at()
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("staff_users.id"))
    resolved_at: Mapped[datetime | None]


class EmergencyAlert(Base):
    __tablename__ = "emergency_alerts"
    __table_args__ = (
        Index(
            "ix_emergency_alerts_unacknowledged",
            "created_at",
            postgresql_where=text("acknowledged_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    patient_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("patients.id", ondelete="RESTRICT"))
    telegram_user_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = _created_at()
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("staff_users.id"))
    acknowledged_at: Mapped[datetime | None]


class ClinicInfo(Base):
    __tablename__ = "clinic_info"

    id: Mapped[uuid.UUID] = _uuid_pk()
    topic: Mapped[str] = mapped_column(unique=True)
    aliases: Mapped[list[str]] = mapped_column(server_default=text("'{}'::text[]"))
    answer: Mapped[str]
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("staff_users.id"))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_ts", text("ts DESC")),
        Index("ix_audit_log_patient_id_ts", "patient_id", text("ts DESC")),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    ts: Mapped[datetime] = mapped_column(server_default=func.now())
    actor_type: Mapped[str]
    actor_id: Mapped[str | None]
    patient_id: Mapped[uuid.UUID | None]
    action: Mapped[str]
    args_json: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
    result: Mapped[str]
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    request_id: Mapped[str | None]
