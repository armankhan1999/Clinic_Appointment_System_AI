"""Synthetic rows for integration tests. Phones use the NANPA fictional range +1 202-555-01xx."""

from datetime import UTC, datetime, time, timedelta
from itertools import count
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession

from clinic.db.models import Appointment, Doctor, DoctorSchedule, Patient

if TYPE_CHECKING:
    from clinic.agent.tools import AgentServices

_phone_suffix = count(100)


def fictional_phone() -> str:
    return f"+1202555{next(_phone_suffix) % 100 + 100:04d}"


async def make_doctor(
    session: AsyncSession,
    *,
    name: str = "Dr. Test",
    specialty: str = "General Physician",
    active: bool = True,
) -> Doctor:
    doctor = Doctor(name=name, specialty=specialty, active=active)
    session.add(doctor)
    await session.flush()
    return doctor


async def add_schedule(
    session: AsyncSession, doctor: Doctor, weekday: int, start: time, end: time, slot_minutes: int = 15
) -> DoctorSchedule:
    row = DoctorSchedule(
        doctor_id=doctor.id, weekday=weekday, start_time=start, end_time=end, slot_minutes=slot_minutes
    )
    session.add(row)
    await session.flush()
    return row


async def make_patient(
    session: AsyncSession,
    *,
    phone: str | None = None,
    telegram_user_id: int | None = None,
    name: str = "Asha Rao",
) -> Patient:
    patient = Patient(
        phone=phone or fictional_phone(),
        full_name=name,
        telegram_user_id=telegram_user_id,
        consent_at=datetime.now(UTC),
        consent_source="telegram" if telegram_user_id else "staff_verbal",
        registered_via="bot" if telegram_user_id else "staff",
    )
    session.add(patient)
    await session.flush()
    return patient


def future_slot(hour: int = 10, minute: int = 0) -> datetime:
    return datetime(2030, 1, 7, hour, minute, tzinfo=UTC)


async def make_appointment(
    session: AsyncSession,
    *,
    doctor: Doctor,
    patient: Patient,
    start: datetime,
    minutes: int = 15,
    status: str = "booked",
) -> Appointment:
    appointment = Appointment(
        doctor_id=doctor.id,
        patient_id=patient.id,
        start_time=start,
        end_time=start + timedelta(minutes=minutes),
        status=status,
        source="bot",
        cancelled_at=datetime.now(UTC) if status == "cancelled" else None,
        cancelled_by_kind="patient" if status == "cancelled" else None,
    )
    session.add(appointment)
    await session.flush()
    return appointment


async def make_clinic_settings(session: AsyncSession) -> None:
    from clinic.db.models import ClinicSettings

    session.add(
        ClinicSettings(
            id=1,
            clinic_name="Demo Family Clinic",
            phone="+12025550100",
            address="12 Example Road",
            staff_hours_text="Monday to Saturday, 9:00 AM to 6:00 PM",
            timezone="Asia/Kolkata",
            emergency_number="112",
            emergency_phrases=["chest pain"],
        )
    )
    await session.flush()


def agent_services(session_factory: object, clock: object | None = None) -> AgentServices:
    """All tool services over one session factory; `clock` pins "now" for availability and booking."""
    from clinic.agent.tools import AgentServices
    from clinic.services.availability import AvailabilityService
    from clinic.services.booking import BookingService
    from clinic.services.clinic_settings import ClinicSettingsService
    from clinic.services.doctors import DoctorService

    factory: Any = session_factory
    settings = ClinicSettingsService(factory)
    extra: dict[str, Any] = {"clock": clock} if clock is not None else {}
    return AgentServices(
        doctors=DoctorService(factory),
        availability=AvailabilityService(factory, settings, **extra),
        booking=BookingService(factory, settings, **extra),
    )
