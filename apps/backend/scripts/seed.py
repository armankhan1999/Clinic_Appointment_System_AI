"""Seed the dev or test schema with a synthetic demo clinic (E7-S1-AC3, GAP-16, GAP-27, GAP-28).

Usage (from apps/backend):
    uv run python scripts/seed.py --target dev
    uv run python scripts/seed.py --target test

Idempotent: existing rows (matched by natural key) are left untouched. Refuses to run when
ENV=production. All data is synthetic: patient phones use the NANPA fictional range
+1 202-555-01xx, and no patient has a Telegram ID, so the bot can never message a real person.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from itertools import cycle
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from clinic.config import DbTarget, get_settings
from clinic.db.models import Appointment, ClinicInfo, ClinicSettings, Doctor, DoctorSchedule, Patient
from clinic.db.session import make_engine, make_session_factory

CLINIC = {
    "clinic_name": "Demo Family Clinic",
    "phone": "+12025550100",
    "address": "12 Example Road, Indiranagar, Bengaluru 560038",
    "staff_hours_text": "Monday to Saturday, 9:00 AM to 6:00 PM",
    "emergency_number": "112",
    "emergency_phrases": [
        "chest pain",
        "can't breathe",
        "cannot breathe",
        "unconscious",
        "severe bleeding",
        "heart attack",
        "stroke",
        "suicide",
    ],
}

MON, TUE, WED, THU, FRI, SAT = range(6)


@dataclass(frozen=True)
class DoctorSeed:
    name: str
    specialty: str
    weekdays: tuple[int, ...]
    blocks: tuple[tuple[time, time], ...]  # two blocks per day = lunch break (GAP-09)
    slot_minutes: int
    slots_per_day: int


DOCTORS = (
    DoctorSeed(
        "Dr. Meera Iyer",
        "General Physician",
        (MON, TUE, WED, THU, FRI, SAT),
        ((time(9), time(13)), (time(14), time(17))),
        15,
        2,
    ),
    DoctorSeed(
        "Dr. Arjun Menon",
        "Paediatrician",
        (MON, WED, FRI),
        ((time(10), time(13)), (time(16), time(19))),
        20,
        1,
    ),
    DoctorSeed(
        "Dr. Kavya Rao", "Dermatologist", (TUE, THU, SAT), ((time(11), time(14)), (time(15), time(18))), 15, 1
    ),
)

FAQ = {
    "timings": (
        ["hours", "opening hours", "open", "timing", "working hours", "closed"],
        "The clinic is open Monday to Saturday, 9:00 AM to 7:00 PM, and closed on Sundays. "
        "Each doctor's consulting hours are shown when you check their free slots.",
    ),
    "fees": (
        ["fee", "cost", "price", "charges", "consultation fee", "payment"],
        "Consultation fees: General Physician Rs 500, Paediatrician Rs 600, Dermatologist Rs 700. "
        "You can pay by cash, card or UPI at the reception.",
    ),
    "address": (
        ["location", "where", "directions", "map", "how to reach"],
        "Demo Family Clinic, 12 Example Road, Indiranagar, Bengaluru 560038. "
        "We are on the ground floor, next to the pharmacy.",
    ),
    "parking": (
        ["park", "car", "vehicle", "bike"],
        "Free parking for cars and two-wheelers is available in the building basement.",
    ),
    "what_to_bring": (
        ["documents", "bring", "prepare", "id", "reports"],
        "Please bring a photo ID, your previous prescriptions and test reports, "
        "and arrive 10 minutes before your appointment.",
    ),
}

PATIENT_NAMES = (
    "Asha Verma",
    "Rahul Nair",
    "Fatima Sheikh",
    "Vikram Singh",
    "Neha Kulkarni",
    "Joseph D'Souza",
    "Priya Reddy",
    "Imran Khan",
)


async def _seed_settings(session: AsyncSession, clinic_timezone: str) -> None:
    if await session.get(ClinicSettings, 1) is None:
        session.add(ClinicSettings(id=1, timezone=clinic_timezone, **CLINIC))


async def _seed_doctors(session: AsyncSession) -> list[tuple[Doctor, DoctorSeed]]:
    seeded = []
    for spec in DOCTORS:
        doctor = await session.scalar(select(Doctor).where(Doctor.name == spec.name))
        if doctor is None:
            doctor = Doctor(name=spec.name, specialty=spec.specialty)
            session.add(doctor)
            await session.flush()
            for weekday in spec.weekdays:
                for start, end in spec.blocks:
                    session.add(
                        DoctorSchedule(
                            doctor_id=doctor.id,
                            weekday=weekday,
                            start_time=start,
                            end_time=end,
                            slot_minutes=spec.slot_minutes,
                        )
                    )
        seeded.append((doctor, spec))
    return seeded


async def _seed_faq(session: AsyncSession) -> None:
    existing = set((await session.scalars(select(ClinicInfo.topic))).all())
    for topic, (aliases, answer) in FAQ.items():
        if topic not in existing:
            session.add(ClinicInfo(topic=topic, aliases=aliases, answer=answer))


async def _seed_patients(session: AsyncSession) -> list[Patient]:
    created = []
    for index, name in enumerate(PATIENT_NAMES, start=1):
        phone = f"+120255501{index:02d}"
        if await session.scalar(select(Patient.id).where(Patient.phone == phone)) is None:
            patient = Patient(
                phone=phone,
                full_name=name,
                consent_at=datetime.now(UTC),
                consent_source="staff_verbal",
                registered_via="staff",
            )
            session.add(patient)
            created.append(patient)
    await session.flush()
    return created


def _slot_starts(spec: DoctorSeed) -> list[time]:
    """First slot of the morning block, then the second slot of the afternoon block."""
    (morning_start, _), (afternoon_start, _) = spec.blocks
    second = (datetime.combine(date.min, afternoon_start) + timedelta(minutes=spec.slot_minutes)).time()
    return [morning_start, second][: spec.slots_per_day]


def _seed_appointments(
    session: AsyncSession,
    doctors: list[tuple[Doctor, DoctorSeed]],
    patients: list[Patient],
    tz: ZoneInfo,
    today: date,
) -> None:
    """Past week completed/no-show, coming week booked, within schedules and per-patient limits."""
    rotation = cycle(patients)
    upcoming: dict[object, int] = {}
    used: set[tuple[object, object, date]] = set()
    past_count = 0
    for offset in [*range(-7, 0), *range(1, 8)]:
        day = today + timedelta(days=offset)
        for doctor, spec in doctors:
            if day.weekday() not in spec.weekdays:
                continue
            for slot in _slot_starts(spec):
                for _ in range(len(patients)):
                    patient = next(rotation)
                    future = offset > 0
                    if (patient.id, doctor.id, day) in used or (future and upcoming.get(patient.id, 0) >= 3):
                        continue
                    break
                else:
                    continue
                start = datetime.combine(day, slot, tzinfo=tz).astimezone(UTC)
                if future:
                    status = "booked"
                    upcoming[patient.id] = upcoming.get(patient.id, 0) + 1
                else:
                    past_count += 1
                    status = "no_show" if past_count % 4 == 0 else "completed"
                used.add((patient.id, doctor.id, day))
                session.add(
                    Appointment(
                        patient_id=patient.id,
                        doctor_id=doctor.id,
                        start_time=start,
                        end_time=start + timedelta(minutes=spec.slot_minutes),
                        status=status,
                        source="staff",
                    )
                )


async def run_seed(
    session_factory: async_sessionmaker[AsyncSession], *, clinic_timezone: str, today: date
) -> None:
    async with session_factory() as session, session.begin():
        await _seed_settings(session, clinic_timezone)
        doctors = await _seed_doctors(session)
        await _seed_faq(session)
        new_patients = await _seed_patients(session)
        if new_patients:
            _seed_appointments(session, doctors, new_patients, ZoneInfo(clinic_timezone), today)


async def _main(target_name: str) -> int:
    settings = get_settings()
    if settings.env == "production":
        print("Refusing to seed: ENV=production. The seed is for dev and test schemas only.", file=sys.stderr)
        return 2
    target = DbTarget.app(settings) if target_name == "dev" else DbTarget.test(settings)
    engine = make_engine(target, settings, null_pool=True)
    try:
        today = datetime.now(ZoneInfo(settings.clinic_timezone)).date()
        await run_seed(make_session_factory(engine), clinic_timezone=settings.clinic_timezone, today=today)
    finally:
        await engine.dispose()
    print(f"Seeded schema '{target.schema}' as {target.role}.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--target", choices=("dev", "test"), required=True)
    sys.exit(asyncio.run(_main(parser.parse_args().target)))
