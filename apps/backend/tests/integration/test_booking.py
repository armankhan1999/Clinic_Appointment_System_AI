"""Booking rules (E2-S3-AC3/AC4, E2-S4-AC1/AC4, GAP-34, MP-04 revalidation)."""

import asyncio
import uuid
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from clinic.db.models import Appointment, AuditLog, Doctor, DoctorLeave
from clinic.domain.results import ResultCode
from clinic.services.booking import BookingService
from clinic.services.clinic_settings import ClinicSettingsService

from .factories import add_schedule, make_clinic_settings, make_doctor, make_patient

Factory = async_sessionmaker[AsyncSession]
IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2030, 1, 7, 8, 0, tzinfo=IST)  # Monday 08:00


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2030, 1, day, hour, minute, tzinfo=IST)


async def _setup(
    session_factory: Factory, patients: int = 1
) -> tuple[list[uuid.UUID], Doctor, BookingService]:
    async with session_factory() as session:
        await make_clinic_settings(session)
        doctor = await make_doctor(session, name="Dr. Meera Iyer")
        for weekday in (0, 1, 2, 3, 4):
            await add_schedule(session, doctor, weekday, time(9), time(11))
        ids = [(await make_patient(session)).id for _ in range(patients)]
        await session.commit()
    service = BookingService(session_factory, ClinicSettingsService(session_factory), clock=lambda: NOW)
    return ids, doctor, service


async def _booked_count(session_factory: Factory) -> int:
    async with session_factory() as session:
        query = select(func.count()).select_from(Appointment).where(Appointment.status == "booked")
        return int(await session.scalar(query) or 0)


async def test_precheck_writes_nothing(session_factory: Factory) -> None:
    [patient], doctor, service = await _setup(session_factory)
    check = await service.precheck(patient, doctor.id, at(7, 9, 30))
    assert check.code == ResultCode.OK
    assert check.doctor_name == "Dr. Meera Iyer"
    assert await _booked_count(session_factory) == 0


async def test_precheck_rejects_slots_that_are_not_bookable(session_factory: Factory) -> None:
    [patient], doctor, service = await _setup(session_factory)
    async with session_factory() as session:
        session.add(DoctorLeave(doctor_id=doctor.id, leave_date=date(2030, 1, 8), reason="Leave"))
        await session.commit()
    for start in (at(7, 9, 7), at(7, 7, 0), at(8, 9, 0), at(5, 9, 0), at(7, 11, 0)):
        assert (await service.precheck(patient, doctor.id, start)).code == ResultCode.SLOT_UNAVAILABLE, start
    assert (await service.precheck(patient, uuid.uuid4(), at(7, 9))).code == ResultCode.NOT_FOUND


async def test_booking_writes_a_referenced_appointment_and_an_audit_row(session_factory: Factory) -> None:
    [patient], doctor, service = await _setup(session_factory)
    outcome = await service.book(
        patient_id=patient, doctor_id=doctor.id, slot_start=at(7, 9, 30), source="bot"
    )
    assert outcome.code == ResultCode.OK
    assert outcome.reference == "APT-000001"
    async with session_factory() as session:
        row = await session.scalar(select(Appointment))
        audit = await session.scalar(select(AuditLog).where(AuditLog.action == "appointment.book"))
    assert row is not None
    assert (row.status, row.source, row.patient_id) == ("booked", "bot", patient)
    assert (row.start_time, row.end_time) == (at(7, 9, 30), at(7, 9, 45))
    assert audit is not None
    assert (audit.result, audit.patient_id) == ("OK", patient)
    assert audit.args_json == {
        "doctor_id": str(doctor.id),
        "slot_start": "2030-01-07T04:00:00+00:00",
        "source": "bot",
    }


async def test_taken_slot_returns_slot_taken_with_nearest_alternatives(session_factory: Factory) -> None:
    [first, second], doctor, service = await _setup(session_factory, patients=2)
    await service.book(patient_id=first, doctor_id=doctor.id, slot_start=at(7, 10), source="bot")
    outcome = await service.book(patient_id=second, doctor_id=doctor.id, slot_start=at(7, 10), source="bot")
    assert outcome.code == ResultCode.SLOT_TAKEN
    # Nearest by distance (ties: earlier first), shown in time order (GAP-34).
    assert [slot.start for slot in outcome.alternatives] == [at(7, 9, 30), at(7, 9, 45), at(7, 10, 15)]
    assert len(outcome.alternatives) == 3
    assert await _booked_count(session_factory) == 1


async def test_one_booking_per_doctor_per_day(session_factory: Factory) -> None:
    [patient], doctor, service = await _setup(session_factory)
    await service.book(patient_id=patient, doctor_id=doctor.id, slot_start=at(7, 9), source="bot")
    outcome = await service.book(patient_id=patient, doctor_id=doctor.id, slot_start=at(7, 10), source="bot")
    assert (outcome.code, outcome.reason) == (ResultCode.LIMIT_REACHED, "same_doctor_same_day")


async def test_at_most_three_upcoming_appointments(session_factory: Factory) -> None:
    [patient], doctor, service = await _setup(session_factory)
    for day in (7, 8, 9):
        outcome = await service.book(
            patient_id=patient, doctor_id=doctor.id, slot_start=at(day, 9), source="bot"
        )
        assert outcome.code == ResultCode.OK
    fourth = await service.book(patient_id=patient, doctor_id=doctor.id, slot_start=at(10, 9), source="bot")
    assert (fourth.code, fourth.reason) == (ResultCode.LIMIT_REACHED, "max_upcoming")
    assert (await service.precheck(patient, doctor.id, at(10, 9))).code == ResultCode.LIMIT_REACHED


async def test_ten_parallel_bookings_for_one_slot_create_exactly_one(session_factory: Factory) -> None:
    patients, doctor, service = await _setup(session_factory, patients=10)
    outcomes = await asyncio.gather(
        *(
            service.book(patient_id=p, doctor_id=doctor.id, slot_start=at(7, 9, 15), source="bot")
            for p in patients
        )
    )
    codes = sorted(o.code for o in outcomes)
    assert codes.count(ResultCode.OK) == 1
    assert codes.count(ResultCode.SLOT_TAKEN) == 9
    assert await _booked_count(session_factory) == 1


async def test_parallel_bookings_by_one_patient_cannot_exceed_the_limit(session_factory: Factory) -> None:
    [patient], doctor, service = await _setup(session_factory)
    await service.book(patient_id=patient, doctor_id=doctor.id, slot_start=at(7, 9), source="bot")
    await service.book(patient_id=patient, doctor_id=doctor.id, slot_start=at(8, 9), source="bot")
    outcomes = await asyncio.gather(
        service.book(patient_id=patient, doctor_id=doctor.id, slot_start=at(9, 9), source="bot"),
        service.book(patient_id=patient, doctor_id=doctor.id, slot_start=at(10, 9), source="bot"),
    )
    assert sorted(o.code for o in outcomes) == [ResultCode.LIMIT_REACHED, ResultCode.OK]
    assert await _booked_count(session_factory) == 3
