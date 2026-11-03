"""Availability (E2-S2-AC1..AC3, E2-S4-AC3, E2-S5-AC3, GAP-33) and the check_availability tool."""

import uuid
from dataclasses import replace
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from clinic.agent.tools import CheckAvailabilityArgs, ToolContext, check_availability
from clinic.db.models import Doctor, DoctorLeave
from clinic.domain.results import ResultCode
from clinic.domain.slots import PartOfDay
from clinic.services.availability import AvailabilityService
from clinic.services.clinic_settings import ClinicSettingsService

from .factories import (
    add_schedule,
    agent_services,
    make_appointment,
    make_clinic_settings,
    make_doctor,
    make_patient,
)

Factory = async_sessionmaker[AsyncSession]
IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2030, 1, 7, 8, 0, tzinfo=IST)  # Monday 08:00 in the clinic
MON, TUE, WED = date(2030, 1, 7), date(2030, 1, 8), date(2030, 1, 9)


async def _setup(session_factory: Factory) -> tuple[uuid.UUID, AvailabilityService]:
    async with session_factory() as session:
        await make_clinic_settings(session)
        doctor = await make_doctor(session, name="Dr. Meera Iyer")
        await add_schedule(session, doctor, 0, time(9), time(10))  # Monday 9-10, 15-minute slots
        await add_schedule(session, doctor, 0, time(14), time(15))
        await add_schedule(session, doctor, 2, time(9), time(10))  # Wednesday
        await session.commit()
    service = AvailabilityService(session_factory, ClinicSettingsService(session_factory), clock=lambda: NOW)
    return doctor.id, service


async def test_free_slots_for_a_day(session_factory: Factory) -> None:
    doctor_id, service = await _setup(session_factory)
    result = await service.day(doctor_id, MON)
    assert result.code == ResultCode.OK
    assert [s.start.astimezone(IST).strftime("%H:%M") for s in result.slots] == [
        "09:00", "09:15", "09:30", "09:45", "14:00", "14:15", "14:30", "14:45",
    ]  # fmt: skip


async def test_part_of_day_filter_and_other_parts_hint(session_factory: Factory) -> None:
    doctor_id, service = await _setup(session_factory)
    afternoon = await service.day(doctor_id, MON, PartOfDay.AFTERNOON)
    assert [s.start.astimezone(IST).hour for s in afternoon.slots] == [14, 14, 14, 14]
    evening = await service.day(doctor_id, MON, PartOfDay.EVENING)
    assert evening.code == ResultCode.NO_SLOTS
    assert evening.other_parts == (PartOfDay.MORNING, PartOfDay.AFTERNOON)


async def test_booked_slots_are_not_offered(session_factory: Factory) -> None:
    doctor_id, service = await _setup(session_factory)
    async with session_factory() as session:
        patient = await make_patient(session)
        doctor = await session.get_one(Doctor, doctor_id)
        await make_appointment(
            session, doctor=doctor, patient=patient, start=datetime(2030, 1, 7, 9, 15, tzinfo=IST)
        )
        await session.commit()
    result = await service.day(doctor_id, MON)
    assert datetime(2030, 1, 7, 9, 15, tzinfo=IST) not in [s.start for s in result.slots]


async def test_no_slots_offers_the_next_three_dates(session_factory: Factory) -> None:
    doctor_id, service = await _setup(session_factory)
    async with session_factory() as session:
        session.add(DoctorLeave(doctor_id=doctor_id, leave_date=WED, reason="Conference"))
        await session.commit()
    result = await service.day(doctor_id, WED)
    assert result.code == ResultCode.NO_SLOTS, "E2-S4-AC3: no slots on a leave day"
    assert result.next_dates == (date(2030, 1, 14), date(2030, 1, 16), date(2030, 1, 21))


async def test_day_the_doctor_does_not_work_suggests_the_next_working_day(session_factory: Factory) -> None:
    doctor_id, service = await _setup(session_factory)
    result = await service.day(doctor_id, TUE)
    assert result.code == ResultCode.DOCTOR_NOT_WORKING
    assert result.next_working_day == WED


async def test_past_and_out_of_window_dates_are_invalid(session_factory: Factory) -> None:
    doctor_id, service = await _setup(session_factory)
    assert (await service.day(doctor_id, date(2030, 1, 6))).code == ResultCode.INVALID_DATE
    assert (await service.day(doctor_id, date(2030, 2, 6))).code == ResultCode.OK  # last day of the window
    assert (await service.day(doctor_id, date(2030, 2, 7))).code == ResultCode.INVALID_DATE


async def test_unknown_or_inactive_doctor_is_not_found(session_factory: Factory) -> None:
    _, service = await _setup(session_factory)
    async with session_factory() as session:
        inactive = await make_doctor(session, name="Dr. Away", active=False)
        await session.commit()
    assert (await service.day(uuid.uuid4(), MON)).code == ResultCode.NOT_FOUND
    assert (await service.day(inactive.id, MON)).code == ResultCode.NOT_FOUND


def _ctx(session_factory: Factory, service: AvailabilityService) -> ToolContext:
    services = replace(agent_services(session_factory, clock=lambda: NOW), availability=service)
    return ToolContext(uuid.uuid4(), "req-avail", services)


async def test_tool_resolves_relative_dates_and_labels_slots(session_factory: Factory) -> None:
    doctor_id, service = await _setup(session_factory)
    args = CheckAvailabilityArgs(doctor_id=doctor_id, date="day after tomorrow", part_of_day="morning")
    result = await check_availability(_ctx(session_factory, service), args)
    assert result.code == ResultCode.OK
    assert result.data["date"] == "Wednesday, 9 January 2030"
    assert result.data["slots"][0] == {"slot_start": "2030-01-09T09:00:00+05:30", "time": "9:00 AM"}
    assert len(result.data["slots"]) == 4


async def test_tool_returns_at_most_five_slots(session_factory: Factory) -> None:
    doctor_id, service = await _setup(session_factory)
    result = await check_availability(
        _ctx(session_factory, service), CheckAvailabilityArgs(doctor_id=doctor_id, date="today")
    )
    assert len(result.data["slots"]) == 5


async def test_tool_reports_ambiguous_and_unrecognised_dates(session_factory: Factory) -> None:
    doctor_id, service = await _setup(session_factory)
    ctx = _ctx(session_factory, service)
    unknown = await check_availability(ctx, CheckAvailabilityArgs(doctor_id=doctor_id, date="someday"))
    assert unknown.code == ResultCode.INVALID_DATE
    past = await check_availability(ctx, CheckAvailabilityArgs(doctor_id=doctor_id, date="2030-01-01"))
    assert past.code == ResultCode.INVALID_DATE


async def test_now_is_utc_aware(session_factory: Factory) -> None:
    _, service = await _setup(session_factory)
    assert service.now().tzinfo is not None
    assert service.now() == NOW.astimezone(UTC)
