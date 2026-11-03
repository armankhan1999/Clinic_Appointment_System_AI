"""E7-S1-AC3: the seed creates doctors, weekly schedules, FAQ entries and synthetic patients."""

import asyncio
import os
import sys
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from clinic.config import Settings
from clinic.db.models import Appointment, ClinicInfo, ClinicSettings, Doctor, DoctorSchedule, Patient
from seed import run_seed

from .conftest import BACKEND_DIR

Factory = async_sessionmaker[AsyncSession]
TODAY = date(2030, 1, 9)  # a Wednesday, far from real data


async def _count(session: AsyncSession, model: type) -> int:
    return int(await session.scalar(select(func.count()).select_from(model)) or 0)


async def test_seed_creates_the_demo_clinic(settings: Settings, session_factory: Factory) -> None:
    await run_seed(session_factory, clinic_timezone=settings.clinic_timezone, today=TODAY)
    async with session_factory() as session:
        assert await _count(session, ClinicSettings) == 1
        doctors = (await session.scalars(select(Doctor))).all()
        assert len(doctors) == 3
        assert all(doctor.active for doctor in doctors)
        schedules = (await session.scalars(select(DoctorSchedule))).all()
        assert {s.doctor_id for s in schedules} == {d.id for d in doctors}
        rows_per_day = Counter((s.doctor_id, s.weekday) for s in schedules)
        assert max(rows_per_day.values()) >= 2, "lunch breaks are modelled as two rows per weekday"
        topics = set((await session.scalars(select(ClinicInfo.topic))).all())
        assert topics == {"timings", "fees", "address", "parking", "what_to_bring"}
        patients = (await session.scalars(select(Patient))).all()
        assert len(patients) == 8
        assert all(p.telegram_user_id is None for p in patients), "synthetic patients must be unreachable"
        assert all(p.phone and p.phone.startswith("+120255501") for p in patients)
        settings_row = await session.get_one(ClinicSettings, 1)
        assert settings_row.timezone == settings.clinic_timezone
        assert settings_row.emergency_number == "112"
        assert "chest pain" in settings_row.emergency_phrases


async def test_seed_appointments_cover_two_weeks_and_respect_rules(
    settings: Settings, session_factory: Factory
) -> None:
    await run_seed(session_factory, clinic_timezone=settings.clinic_timezone, today=TODAY)
    tz = ZoneInfo(settings.clinic_timezone)
    async with session_factory() as session:
        appointments = (await session.scalars(select(Appointment))).all()
        schedules = (await session.scalars(select(DoctorSchedule))).all()
    assert appointments
    start_of_today = datetime.combine(TODAY, datetime.min.time(), tzinfo=tz)
    for appt in appointments:
        local = appt.start_time.astimezone(tz)
        assert TODAY - timedelta(days=7) <= local.date() <= TODAY + timedelta(days=7)
        if appt.status == "booked":
            assert appt.start_time > start_of_today
        else:
            assert appt.status in {"completed", "no_show"}
            assert appt.end_time <= start_of_today
        matching = [
            s
            for s in schedules
            if s.doctor_id == appt.doctor_id
            and s.weekday == local.weekday()
            and s.start_time <= local.time()
            and (local + timedelta(minutes=s.slot_minutes)).time() <= s.end_time
        ]
        assert matching, f"{appt.ref} is outside the doctor's schedule"
        assert appt.end_time - appt.start_time == timedelta(minutes=matching[0].slot_minutes)
    booked = [a for a in appointments if a.status == "booked"]
    assert max(Counter(a.patient_id for a in booked).values()) <= 3
    per_doctor_day = Counter((a.patient_id, a.doctor_id, a.start_time.astimezone(tz).date()) for a in booked)
    assert max(per_doctor_day.values()) == 1
    assert {a.status for a in appointments} >= {"booked", "completed", "no_show"}


async def test_seed_is_idempotent(settings: Settings, session_factory: Factory) -> None:
    await run_seed(session_factory, clinic_timezone=settings.clinic_timezone, today=TODAY)
    async with session_factory() as session:
        first = [await _count(session, m) for m in (Doctor, DoctorSchedule, ClinicInfo, Patient, Appointment)]
    await run_seed(session_factory, clinic_timezone=settings.clinic_timezone, today=TODAY)
    async with session_factory() as session:
        second = [
            await _count(session, m) for m in (Doctor, DoctorSchedule, ClinicInfo, Patient, Appointment)
        ]
    assert first == second


async def test_seed_refuses_to_run_in_production(session_factory: Factory) -> None:
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "scripts/seed.py",
        "--target",
        "test",
        cwd=BACKEND_DIR,
        env={**os.environ, "ENV": "production"},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    assert process.returncode != 0
    assert b"production" in stderr
    async with session_factory() as session:
        assert await _count(session, Doctor) == 0


def test_today_constant_is_a_wednesday() -> None:
    assert TODAY.weekday() == 2
    assert datetime(2030, 1, 9, tzinfo=UTC).date() == TODAY
