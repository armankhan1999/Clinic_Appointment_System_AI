"""Core services: clinic settings, doctors (E2-S1), audit (E7-S2), tickets (E5-S4-AC3)."""

import uuid
from datetime import time

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from clinic.db.models import AuditLog, ClinicSettings, HandoffTicket
from clinic.domain.results import ResultCode
from clinic.observability import bind_request_id
from clinic.services.audit import AuditService, ForbiddenAuditFieldError
from clinic.services.clinic_settings import ClinicSettingsMissingError, ClinicSettingsService
from clinic.services.doctors import DoctorService
from clinic.services.tickets import TicketService

from .factories import add_schedule, make_doctor, make_patient

Factory = async_sessionmaker[AsyncSession]


async def _add_settings(session_factory: Factory) -> None:
    async with session_factory() as session:
        session.add(
            ClinicSettings(
                id=1,
                clinic_name="Test Clinic",
                phone="+12025550100",
                address="1 Example Road",
                staff_hours_text="Mon-Sat 9-6",
                timezone="Asia/Kolkata",
                emergency_number="112",
                emergency_phrases=["chest pain"],
            )
        )
        await session.commit()


async def test_settings_view_exposes_clinic_configuration(session_factory: Factory) -> None:
    await _add_settings(session_factory)
    view = await ClinicSettingsService(session_factory).get()
    assert view.clinic_name == "Test Clinic"
    assert view.tz.key == "Asia/Kolkata"
    assert view.emergency_phrases == ("chest pain",)
    assert (view.cutoff_minutes, view.booking_window_days) == (120, 30)
    assert (view.morning_end, view.afternoon_end) == (time(12), time(17))


async def test_settings_are_cached_until_the_ttl_expires(session_factory: Factory) -> None:
    await _add_settings(session_factory)
    now = [0.0]
    service = ClinicSettingsService(session_factory, ttl_seconds=30, clock=lambda: now[0])
    assert (await service.get()).clinic_name == "Test Clinic"
    async with session_factory() as session:
        row = await session.get_one(ClinicSettings, 1)
        row.clinic_name = "Renamed Clinic"
        await session.commit()
    now[0] = 29.0
    assert (await service.get()).clinic_name == "Test Clinic"
    now[0] = 31.0
    assert (await service.get()).clinic_name == "Renamed Clinic"


async def test_missing_settings_fail_loudly(session_factory: Factory) -> None:
    with pytest.raises(ClinicSettingsMissingError):
        await ClinicSettingsService(session_factory).get()


async def test_list_active_doctors_with_working_days(session_factory: Factory) -> None:
    async with session_factory() as session:
        derm = await make_doctor(session, name="Dr. Skin", specialty="Dermatologist")
        await add_schedule(session, derm, 1, time(10), time(13))
        await add_schedule(session, derm, 1, time(14), time(17))
        await add_schedule(session, derm, 3, time(10), time(13))
        gp = await make_doctor(session, name="Dr. General", specialty="General Physician")
        await add_schedule(session, gp, 0, time(9), time(17))
        await make_doctor(session, name="Dr. Gone", specialty="Dermatologist", active=False)
        await session.commit()
    doctors = await DoctorService(session_factory).list_active()
    assert [d.name for d in doctors] == ["Dr. General", "Dr. Skin"]
    assert doctors[1].working_weekdays == (1, 3)
    assert doctors[0].working_weekdays == (0,)


async def test_inactive_doctor_never_appears(session_factory: Factory) -> None:
    async with session_factory() as session:
        await make_doctor(session, name="Dr. Gone", specialty="Dermatologist", active=False)
        await session.commit()
    assert await DoctorService(session_factory).list_active() == []
    assert await DoctorService(session_factory).list_active("derma") == []


async def test_specialty_filter_is_case_insensitive_and_wildcard_safe(session_factory: Factory) -> None:
    async with session_factory() as session:
        await make_doctor(session, name="Dr. Skin", specialty="Dermatologist")
        await make_doctor(session, name="Dr. Kids", specialty="Paediatrician")
        await session.commit()
    service = DoctorService(session_factory)
    assert [d.name for d in await service.list_active("DERMA")] == ["Dr. Skin"]
    assert await service.list_active("neurology") == []
    assert await service.list_active("%") == [], "LIKE wildcards in input must be literal"
    assert await service.list_active("_") == []


async def test_doctor_without_schedule_has_no_working_days(session_factory: Factory) -> None:
    async with session_factory() as session:
        await make_doctor(session, name="Dr. New")
        await session.commit()
    [doctor] = await DoctorService(session_factory).list_active()
    assert doctor.working_weekdays == ()


async def test_audit_row_has_every_required_field(session_factory: Factory) -> None:
    patient_id = uuid.uuid4()
    async with session_factory() as session:
        with bind_request_id("req-audit-0001"):
            AuditService.record(
                session,
                actor_type="agent",
                actor_id="gemini-3.5-flash-lite",
                action="list_doctors",
                args={"specialty": "derma"},
                result=ResultCode.OK,
                patient_id=patient_id,
                latency_ms=42,
            )
        await session.commit()
        row = await session.scalar(select(AuditLog))
    assert row is not None
    assert row.ts is not None
    assert (row.actor_type, row.action, row.result) == ("agent", "list_doctors", "OK")
    assert row.args_json == {"specialty": "derma"}
    assert row.patient_id == patient_id
    assert row.latency_ms == 42
    assert row.request_id == "req-audit-0001"


@pytest.mark.parametrize("key", ["text", "message", "name", "phone", "full_name"])
async def test_audit_refuses_chat_text_and_personal_fields(session_factory: Factory, key: str) -> None:
    async with session_factory() as session:
        with pytest.raises(ForbiddenAuditFieldError):
            AuditService.record(
                session,
                actor_type="agent",
                actor_id=None,
                action="list_doctors",
                args={"nested": {key: "value"}},
                result=ResultCode.OK,
                patient_id=None,
                latency_ms=None,
            )


async def test_ticket_is_created_once_per_open_issue(session_factory: Factory) -> None:
    async with session_factory() as session:
        patient = await make_patient(session)
        await session.commit()
    async with session_factory() as session, session.begin():
        first = await TicketService.open_or_get(session, patient_id=patient.id, reason="patient_requested")
    async with session_factory() as session, session.begin():
        second = await TicketService.open_or_get(session, patient_id=patient.id, reason="agent_failed")
    assert first[0] == ResultCode.CREATED
    assert second == (ResultCode.ALREADY_OPEN, first[1])
    async with session_factory() as session:
        tickets = (await session.scalars(select(HandoffTicket))).all()
    assert len(tickets) == 1
    assert tickets[0].reason == "patient_requested"
