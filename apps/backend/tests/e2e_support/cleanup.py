"""Deletes rows the E2E specs created, and only those: every row must carry the E2E marker.

    uv run python -m tests.e2e_support.cleanup --patient <uuid> --doctor <uuid> --staff e2e_tmp_name

A patient goes with its appointments (and their reminders and notifications), handoff tickets and
emergency alerts; a doctor with its weekly hours and leave days (refused while it has appointments); a
staff account with its sessions. The audit log is append-only and keeps its rows. Ids that no longer
exist are reported under "missing", so clean-up can run twice. Prints {"deleted": {...}, "missing": [...]}.
"""

import argparse
import sys
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from clinic.db.models import (
    Appointment,
    Doctor,
    DoctorLeave,
    DoctorSchedule,
    EmergencyAlert,
    HandoffTicket,
    Notification,
    Patient,
    Reminder,
    StaffUser,
)
from tests.e2e_support.common import MARKER, STAFF_MARKER, Fixture, FixtureError, run


def is_e2e_patient(patient: Patient) -> bool:
    return (
        (patient.full_name or "").startswith(MARKER)
        and patient.registered_via == "staff"
        and patient.telegram_user_id is None
    )


async def _delete_patient(session: AsyncSession, patient_id: UUID) -> bool:
    patient = await session.get(Patient, patient_id, with_for_update=True)
    if patient is None:
        return False
    if not is_e2e_patient(patient):
        raise FixtureError(f"patient {patient_id} is not an E2E patient")
    appointments = select(Appointment.id).where(Appointment.patient_id == patient_id)
    await session.execute(delete(Reminder).where(Reminder.appointment_id.in_(appointments)))
    await session.execute(delete(Notification).where(Notification.patient_id == patient_id))
    await session.execute(delete(Appointment).where(Appointment.patient_id == patient_id))
    await session.execute(delete(HandoffTicket).where(HandoffTicket.patient_id == patient_id))
    await session.execute(delete(EmergencyAlert).where(EmergencyAlert.patient_id == patient_id))
    await session.execute(delete(Patient).where(Patient.id == patient_id))
    return True


async def _delete_doctor(session: AsyncSession, doctor_id: UUID) -> bool:
    doctor = await session.get(Doctor, doctor_id, with_for_update=True)
    if doctor is None:
        return False
    if not doctor.name.startswith(MARKER):
        raise FixtureError(f"doctor {doctor_id} is not an E2E doctor")
    if await session.scalar(select(func.count()).where(Appointment.doctor_id == doctor_id)):
        raise FixtureError(f"doctor {doctor_id} has appointments; delete those patients first")
    await session.execute(delete(DoctorSchedule).where(DoctorSchedule.doctor_id == doctor_id))
    await session.execute(delete(DoctorLeave).where(DoctorLeave.doctor_id == doctor_id))
    await session.execute(delete(Doctor).where(Doctor.id == doctor_id))
    return True


async def _delete_staff(session: AsyncSession, username: str) -> bool:
    if not username.startswith(STAFF_MARKER):
        raise FixtureError(f"{username!r} is not an E2E staff username")
    user = await session.scalar(select(StaffUser).where(StaffUser.username == username).with_for_update())
    if user is None:
        return False
    await session.execute(delete(StaffUser).where(StaffUser.id == user.id))  # sessions cascade
    return True


def fixture(args: argparse.Namespace) -> Fixture:
    async def clean(session_factory: async_sessionmaker[AsyncSession]) -> dict[str, Any]:
        deleted: dict[str, list[str]] = {"patients": [], "doctors": [], "staff": []}
        missing: list[str] = []
        async with session_factory() as session, session.begin():
            for patient_id in args.patient:
                (deleted["patients"] if await _delete_patient(session, patient_id) else missing).append(
                    str(patient_id)
                )
            for doctor_id in args.doctor:
                (deleted["doctors"] if await _delete_doctor(session, doctor_id) else missing).append(
                    str(doctor_id)
                )
            for username in args.staff:
                (deleted["staff"] if await _delete_staff(session, username) else missing).append(username)
        return {"deleted": deleted, "missing": missing}

    return clean


def _arguments(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--patient", type=UUID, action="append", default=[])
    parser.add_argument("--doctor", type=UUID, action="append", default=[])
    parser.add_argument("--staff", action="append", default=[])
    return parser.parse_args(argv)


if __name__ == "__main__":
    sys.exit(run(fixture(_arguments(sys.argv[1:]))))
