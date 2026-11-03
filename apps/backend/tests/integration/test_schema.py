"""Database rules that must hold regardless of application code (BR-03, E2-S4-AC2, E7-S2, D-20)."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import (
    BigInteger,
    Column,
    Connection,
    Integer,
    MetaData,
    Table,
    delete,
    func,
    literal,
    select,
    text,
    update,
)
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.schema import CreateTable

from clinic.config import Settings
from clinic.db.models import AuditLog, Base, HandoffTicket, Patient, Reminder

from .factories import future_slot, make_appointment, make_doctor, make_patient

EXPECTED_TABLES = {
    "clinic_settings", "staff_users", "staff_sessions", "doctors", "doctor_schedules", "doctor_leaves",
    "patients", "appointments", "reminders", "notifications", "handoff_tickets", "emergency_alerts",
    "clinic_info", "audit_log",
}  # fmt: skip

Factory = async_sessionmaker[AsyncSession]


def sqlstate(exc: DBAPIError) -> Any:
    return getattr(exc.orig, "sqlstate", None)


async def test_every_table_exists_with_row_level_security(
    settings: Settings, session_factory: Factory
) -> None:
    async with session_factory() as session:
        rows = await session.execute(
            text(
                "select c.relname, c.relrowsecurity from pg_class c "
                "join pg_namespace n on n.oid = c.relnamespace "
                "where n.nspname = :schema and c.relkind = 'r' and c.relname <> 'alembic_version'"
            ),
            {"schema": settings.db_test_schema},
        )
        found: dict[str, bool] = dict(rows.all())
    assert set(found) == EXPECTED_TABLES
    assert all(found.values()), {name for name, rls in found.items() if not rls}


async def test_partial_unique_index_on_booked_slots_exists(
    settings: Settings, session_factory: Factory
) -> None:
    async with session_factory() as session:
        indexdef = await session.scalar(
            text("select indexdef from pg_indexes where schemaname = :schema and indexname = :name"),
            {"schema": settings.db_test_schema, "name": "ux_appt_doctor_start_booked"},
        )
    assert indexdef is not None
    assert "CREATE UNIQUE INDEX" in indexdef
    assert "(doctor_id, start_time)" in indexdef
    assert "WHERE (status = 'booked'::text)" in indexdef


async def test_second_booking_for_same_doctor_and_start_is_rejected(session_factory: Factory) -> None:
    async with session_factory() as session:
        doctor = await make_doctor(session)
        first, second = await make_patient(session), await make_patient(session)
        await make_appointment(session, doctor=doctor, patient=first, start=future_slot())
        await session.commit()
    async with session_factory() as session:
        with pytest.raises(IntegrityError):
            await make_appointment(session, doctor=doctor, patient=second, start=future_slot())


async def test_cancelled_rows_do_not_block_the_slot(session_factory: Factory) -> None:
    async with session_factory() as session:
        doctor = await make_doctor(session)
        patient = await make_patient(session)
        await make_appointment(
            session, doctor=doctor, patient=patient, start=future_slot(), status="cancelled"
        )
        await make_appointment(
            session, doctor=doctor, patient=patient, start=future_slot(), status="cancelled"
        )
        await make_appointment(session, doctor=doctor, patient=patient, start=future_slot())
        await session.commit()


async def test_overlapping_booking_with_different_start_is_rejected(session_factory: Factory) -> None:
    async with session_factory() as session:
        doctor = await make_doctor(session)
        patient = await make_patient(session)
        await make_appointment(session, doctor=doctor, patient=patient, start=future_slot(10, 0))
        await session.commit()
    async with session_factory() as session:
        with pytest.raises(IntegrityError):
            await make_appointment(
                session, doctor=doctor, patient=patient, start=future_slot(9, 50), minutes=20
            )


async def test_back_to_back_bookings_are_allowed(session_factory: Factory) -> None:
    async with session_factory() as session:
        doctor = await make_doctor(session)
        patient = await make_patient(session)
        await make_appointment(session, doctor=doctor, patient=patient, start=future_slot(10, 0))
        await make_appointment(session, doctor=doctor, patient=patient, start=future_slot(10, 15))
        await session.commit()


async def test_references_are_sequential_and_zero_padded(session_factory: Factory) -> None:
    async with session_factory() as session:
        doctor = await make_doctor(session)
        patient = await make_patient(session)
        first = await make_appointment(session, doctor=doctor, patient=patient, start=future_slot(10, 0))
        second = await make_appointment(session, doctor=doctor, patient=patient, start=future_slot(11, 0))
        await session.commit()
        await session.refresh(first)
        await session.refresh(second)
    assert (first.ref, second.ref) == ("APT-000001", "APT-000002")


async def test_reference_format_keeps_growing_past_six_digits(
    settings: Settings, session_factory: Factory
) -> None:
    schema_functions = getattr(func, settings.db_test_schema)
    async with session_factory() as session:
        big = await session.scalar(
            select(schema_functions.format_appointment_ref(literal(1234567, BigInteger)))
        )
        small = await session.scalar(select(schema_functions.format_appointment_ref(literal(42, BigInteger))))
    assert (big, small) == ("APT-1234567", "APT-000042")


async def test_audit_log_is_insert_and_select_only_for_the_app_role(
    settings: Settings, session_factory: Factory
) -> None:
    async with session_factory() as session:
        session.add(AuditLog(actor_type="system", action="test.write", args_json={}, result="OK"))
        await session.commit()
    for statement in (update(AuditLog).values(result="X"), delete(AuditLog)):
        async with session_factory() as session:
            with pytest.raises(DBAPIError) as caught:
                await session.execute(statement)
            assert sqlstate(caught.value) == "42501"


async def test_audit_log_trigger_blocks_changes_even_for_the_owner(
    session_factory: Factory, migrator_engine: AsyncEngine, settings: Settings
) -> None:
    async with session_factory() as session:
        session.add(AuditLog(actor_type="system", action="test.write", args_json={}, result="OK"))
        await session.commit()
    async with migrator_engine.connect() as conn:
        with pytest.raises(DBAPIError, match="append-only"):
            await conn.execute(update(AuditLog).values(result="X"))


async def test_app_role_cannot_create_tables(settings: Settings, session_factory: Factory) -> None:
    async with session_factory() as session:
        with pytest.raises(DBAPIError) as caught:
            await session.execute(CreateTable(Table("intruder", MetaData(), Column("id", Integer))))
    assert sqlstate(caught.value) == "42501"


async def test_test_role_cannot_reach_the_dev_schema(settings: Settings, session_factory: Factory) -> None:
    async with session_factory() as session:
        allowed = await session.scalar(
            text("select has_schema_privilege(current_user, :schema, 'USAGE')"),
            {"schema": settings.db_schema},
        )
    assert allowed is False


async def test_patient_without_identity_is_rejected_unless_deleted(session_factory: Factory) -> None:
    async with session_factory() as session:
        session.add(Patient(registered_via="bot"))
        with pytest.raises(IntegrityError):
            await session.flush()
    async with session_factory() as session:
        session.add(Patient(registered_via="bot", full_name="Deleted patient", deleted_at=datetime.now(UTC)))
        await session.commit()


async def test_only_one_open_handoff_ticket_per_patient(session_factory: Factory) -> None:
    async with session_factory() as session:
        patient = await make_patient(session)
        ticket = HandoffTicket(patient_id=patient.id, reason="patient_requested")
        session.add(ticket)
        await session.commit()
    async with session_factory() as session:
        session.add(HandoffTicket(patient_id=patient.id, reason="agent_failed"))
        with pytest.raises(IntegrityError):
            await session.flush()
    async with session_factory() as session:
        stored = await session.get_one(HandoffTicket, ticket.id)
        stored.status = "resolved"
        stored.resolved_at = datetime.now(UTC)
        session.add(HandoffTicket(patient_id=patient.id, reason="agent_failed"))
        await session.commit()


async def test_one_reminder_per_appointment_and_type(session_factory: Factory) -> None:
    async with session_factory() as session:
        doctor = await make_doctor(session)
        patient = await make_patient(session)
        appointment = await make_appointment(
            session, doctor=doctor, patient=patient, start=datetime.now(UTC) + timedelta(days=2)
        )
        session.add(Reminder(appointment_id=appointment.id, type="24h"))
        await session.commit()
    async with session_factory() as session:
        session.add(Reminder(appointment_id=appointment.id, type="24h"))
        with pytest.raises(IntegrityError):
            await session.flush()


def _diff(connection: Connection) -> list[Any]:
    context = MigrationContext.configure(
        connection, opts={"compare_type": True, "compare_server_default": False}
    )
    return list(compare_metadata(context, Base.metadata))


async def test_models_match_the_migrated_schema(settings: Settings, migrator_engine: AsyncEngine) -> None:
    async with migrator_engine.connect() as conn:
        await conn.execute(text(f'set search_path to "{settings.db_test_schema}"'))
        differences = await conn.run_sync(_diff)
    assert differences == []


async def test_reference_is_available_right_after_flush(session_factory: Factory) -> None:
    async with session_factory() as session:
        doctor = await make_doctor(session)
        patient = await make_patient(session)
        appointment = await make_appointment(session, doctor=doctor, patient=patient, start=future_slot())
        assert appointment.ref == "APT-000001"


async def test_deleted_patient_must_be_anonymised(session_factory: Factory) -> None:
    async with session_factory() as session:
        session.add(
            Patient(
                registered_via="bot",
                full_name="Deleted patient",
                phone="+12025550199",
                deleted_at=datetime.now(UTC),
            )
        )
        with pytest.raises(IntegrityError, match="ck_patients_deleted_anonymised"):
            await session.flush()
    async with session_factory() as session:
        session.add(
            Patient(
                registered_via="bot",
                full_name="Deleted patient",
                telegram_user_id=5,
                deleted_at=datetime.now(UTC),
            )
        )
        with pytest.raises(IntegrityError, match="ck_patients_deleted_anonymised"):
            await session.flush()
