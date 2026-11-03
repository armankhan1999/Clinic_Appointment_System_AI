"""Manage appointments: E3-S1 (list, scoping), E3-S2 (reschedule), E3-S3 (cancel), cut-off, GAP-20, GAP-31."""

import uuid
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from clinic.db.models import Appointment, AuditLog, Doctor, Patient
from clinic.domain.appointments import within_cutoff
from clinic.domain.results import ResultCode
from clinic.services.booking import BookingService
from clinic.services.clinic_settings import ClinicSettingsService

from .factories import add_schedule, make_appointment, make_clinic_settings, make_doctor, make_patient

Factory = async_sessionmaker[AsyncSession]
IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2030, 1, 7, 8, 0, tzinfo=IST)  # Monday 08:00


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2030, 1, day, hour, minute, tzinfo=IST)


async def _setup(session_factory: Factory) -> tuple[uuid.UUID, uuid.UUID, Doctor, BookingService]:
    async with session_factory() as session:
        await make_clinic_settings(session)
        doctor = await make_doctor(session, name="Dr. Meera Iyer")
        for weekday in range(5):
            await add_schedule(session, doctor, weekday, time(9), time(11))
        mine = await make_patient(session)
        other = await make_patient(session)
        await session.commit()
    return (
        mine.id,
        other.id,
        doctor,
        BookingService(session_factory, ClinicSettingsService(session_factory), clock=lambda: NOW),
    )


async def _book(
    session_factory: Factory, doctor: Doctor, patient_id: uuid.UUID, start: datetime
) -> Appointment:
    async with session_factory() as session:
        patient = await session.get_one(Patient, patient_id)
        appointment = await make_appointment(session, doctor=doctor, patient=patient, start=start)
        await session.commit()
        return appointment


def test_cutoff_includes_the_boundary_and_the_past() -> None:
    assert within_cutoff(NOW + timedelta(minutes=119), NOW, 120)
    assert not within_cutoff(NOW + timedelta(minutes=120), NOW, 120)
    assert within_cutoff(NOW - timedelta(minutes=5), NOW, 120)


async def test_upcoming_list_is_soonest_first_and_scoped_to_the_patient(session_factory: Factory) -> None:
    mine, other, doctor, service = await _setup(session_factory)
    later = await _book(session_factory, doctor, mine, at(9, 9))
    sooner = await _book(session_factory, doctor, mine, at(8, 9))
    await _book(session_factory, doctor, other, at(8, 10))
    listed = await service.upcoming_for_patient(mine)
    assert [a.reference for a in listed] == [sooner.ref, later.ref]
    assert listed[0].doctor_name == "Dr. Meera Iyer"


async def test_another_patients_reference_is_not_found(session_factory: Factory) -> None:
    mine, other, doctor, service = await _setup(session_factory)
    theirs = await _book(session_factory, doctor, other, at(8, 10))
    assert (await service.check_change(mine, theirs.ref)).code == ResultCode.NOT_FOUND
    assert (await service.check_change(mine, "APT-999999")).code == ResultCode.NOT_FOUND


async def test_cancel_frees_the_slot_and_a_second_cancel_changes_nothing(session_factory: Factory) -> None:
    mine, _, doctor, service = await _setup(session_factory)
    appointment = await _book(session_factory, doctor, mine, at(8, 9))
    first = await service.cancel(patient_id=mine, appointment_id=appointment.id)
    second = await service.cancel(patient_id=mine, appointment_id=appointment.id)
    assert (first.code, second.code) == (ResultCode.OK, ResultCode.ALREADY_CANCELLED)
    async with session_factory() as session:
        stored = await session.get_one(Appointment, appointment.id)
        audit = (await session.scalars(select(AuditLog).where(AuditLog.action == "appointment.cancel"))).all()
    assert (stored.status, stored.cancelled_by_kind) == ("cancelled", "patient")
    assert stored.cancelled_at is not None
    assert [a.result for a in audit] == ["OK", "ALREADY_CANCELLED"]
    rebooked = await service.book(patient_id=mine, doctor_id=doctor.id, slot_start=at(8, 9), source="bot")
    assert rebooked.code == ResultCode.OK, "E3-S3-AC2: the slot is free again"


async def test_changes_within_the_cutoff_are_refused(session_factory: Factory) -> None:
    mine, _, doctor, service = await _setup(session_factory)
    soon = await _book(session_factory, doctor, mine, at(7, 9, 45))  # 1 h 45 min from now
    assert (await service.check_change(mine, soon.ref)).code == ResultCode.WITHIN_CUTOFF
    assert (await service.cancel(patient_id=mine, appointment_id=soon.id)).code == ResultCode.WITHIN_CUTOFF
    moved = await service.reschedule(patient_id=mine, appointment_id=soon.id, new_slot_start=at(8, 9))
    assert moved.code == ResultCode.WITHIN_CUTOFF


async def test_reschedule_creates_a_linked_booking_and_cancels_the_old_one(session_factory: Factory) -> None:
    mine, _, doctor, service = await _setup(session_factory)
    old = await _book(session_factory, doctor, mine, at(8, 9))
    outcome = await service.reschedule(patient_id=mine, appointment_id=old.id, new_slot_start=at(9, 10))
    assert outcome.code == ResultCode.OK
    assert outcome.old_reference == old.ref
    assert outcome.reference is not None
    assert outcome.reference != old.ref, "GAP-31: a reschedule gets a new reference"
    async with session_factory() as session:
        rows = {a.ref: a for a in (await session.scalars(select(Appointment))).all()}
    assert rows[old.ref].status == "cancelled"
    assert rows[outcome.reference].status == "booked"
    assert rows[outcome.reference].rescheduled_from == old.id
    assert rows[outcome.reference].start_time == at(9, 10)


async def test_reschedule_to_a_taken_slot_leaves_the_old_booking_unchanged(session_factory: Factory) -> None:
    mine, other, doctor, service = await _setup(session_factory)
    old = await _book(session_factory, doctor, mine, at(8, 9))
    await _book(session_factory, doctor, other, at(9, 10))
    outcome = await service.reschedule(patient_id=mine, appointment_id=old.id, new_slot_start=at(9, 10))
    assert outcome.code == ResultCode.SLOT_TAKEN
    assert len(outcome.alternatives) == 3
    async with session_factory() as session:
        assert (await session.get_one(Appointment, old.id)).status == "booked"


async def test_reschedule_does_not_count_the_appointment_being_moved(session_factory: Factory) -> None:
    mine, _, doctor, service = await _setup(session_factory)
    for day in (8, 9):
        await _book(session_factory, doctor, mine, at(day, 9))
    third = await _book(session_factory, doctor, mine, at(10, 9))
    same_day = await service.reschedule(patient_id=mine, appointment_id=third.id, new_slot_start=at(10, 10))
    assert same_day.code == ResultCode.OK, "GAP-20: neither the 3-upcoming nor the same-day limit counts it"


async def test_other_patients_cannot_cancel_or_move_my_booking(session_factory: Factory) -> None:
    mine, other, doctor, service = await _setup(session_factory)
    appointment = await _book(session_factory, doctor, mine, at(8, 9))
    assert (
        await service.cancel(patient_id=other, appointment_id=appointment.id)
    ).code == ResultCode.NOT_FOUND
    moved = await service.reschedule(patient_id=other, appointment_id=appointment.id, new_slot_start=at(9, 9))
    assert moved.code == ResultCode.NOT_FOUND
