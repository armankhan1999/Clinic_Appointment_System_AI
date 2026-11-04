"""Plumbing shared by the E2E fixtures: dev schema only, never production, one JSON document on stdout.

Run from apps/backend, for example `uv run python -m tests.e2e_support.attention_fixture`. Every row a
fixture creates is marked: patient and doctor names start with MARKER, staff usernames with
STAFF_MARKER. `cleanup` refuses rows without the marker, so seed data and real records are never touched.
"""

import asyncio
import json
import secrets
import string
import sys
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from clinic.config import DbTarget, Settings, get_settings
from clinic.db.models import Appointment, Doctor, Patient
from clinic.db.session import make_engine, make_session_factory
from clinic.domain.slots import format_time_12h

MARKER = "Playwright "
STAFF_MARKER = "e2e_tmp_"
# NANPA numbers reserved for fiction, +1 202-555-0110..0199; the seed uses 0101-0108.
FICTIONAL_PHONES = tuple(f"+120255501{n:02d}" for n in range(10, 100))

type Fixture = Callable[[async_sessionmaker[AsyncSession]], Awaitable[dict[str, Any]]]


class FixtureError(RuntimeError):
    """The fixture cannot do what was asked without touching rows it does not own."""


def random_letters(length: int = 6) -> str:
    """Patient names may not contain digits (ck_patients_full_name), so uniqueness comes from letters."""
    return "".join(secrets.choice(string.ascii_lowercase) for _ in range(length)).capitalize()


def run(fixture: Fixture) -> int:
    """Refuses ENV=production, runs `fixture` against the dev schema and prints its result as JSON."""
    structlog.configure(logger_factory=structlog.PrintLoggerFactory(sys.stderr))  # stdout is the JSON
    settings = get_settings()
    if settings.env == "production":
        print("Refusing to run: ENV=production. E2E fixtures write to the dev schema only.", file=sys.stderr)
        return 2
    try:
        result = asyncio.run(_run(fixture, settings))
    except FixtureError as exc:
        print(f"E2E fixture refused: {exc}", file=sys.stderr)
        return 3
    print(json.dumps(result, default=str))
    return 0


async def _run(fixture: Fixture, settings: Settings) -> dict[str, Any]:
    engine = make_engine(DbTarget.app(settings), settings, null_pool=True)
    try:
        return await fixture(make_session_factory(engine))
    finally:
        await engine.dispose()


async def new_patient(session: AsyncSession, label: str, now: datetime) -> Patient:
    """A staff-registered patient with a fictional phone and no Telegram link, so nobody is ever messaged."""
    taken = set(
        (await session.scalars(select(Patient.phone).where(Patient.phone.in_(FICTIONAL_PHONES)))).all()
    )
    free = [phone for phone in FICTIONAL_PHONES if phone not in taken]
    if not free:
        raise FixtureError("every fictional phone number is in use; clean up leftover E2E patients first")
    patient = Patient(
        phone=secrets.choice(free),
        full_name=f"{MARKER}{label} {random_letters()}",
        consent_at=now,
        consent_source="staff_verbal",
        registered_via="staff",
    )
    session.add(patient)
    await session.flush()
    return patient


async def active_doctor(session: AsyncSession, doctor_id: UUID | None) -> Doctor:
    query = select(Doctor).where(Doctor.active.is_(True))
    if doctor_id is not None:
        query = query.where(Doctor.id == doctor_id)
    doctor = await session.scalar(query.order_by(Doctor.name).limit(1))
    if doctor is None:
        raise FixtureError("no active doctor" if doctor_id is None else f"doctor {doctor_id} is not active")
    return doctor


def first_free_start(
    start: datetime, length: timedelta, booked: Sequence[tuple[datetime, datetime]], step: timedelta
) -> datetime:
    """`start`, moved by `step` until [start, start + length) overlaps no booked range (no-overlap rule)."""
    candidate = start
    for _ in range(96):
        end = candidate + length
        if not any(other_start < end and candidate < other_end for other_start, other_end in booked):
            return candidate
        candidate += step
    raise FixtureError(f"no free {length} near {start.isoformat()} for this doctor")


async def booked_ranges(
    session: AsyncSession, doctor_id: UUID, around: datetime
) -> list[tuple[datetime, datetime]]:
    rows = await session.execute(
        select(Appointment.start_time, Appointment.end_time).where(
            Appointment.doctor_id == doctor_id,
            Appointment.status == "booked",
            Appointment.end_time > around - timedelta(days=2),
            Appointment.start_time < around + timedelta(days=2),
        )
    )
    return [(row.start_time, row.end_time) for row in rows]


async def add_appointments(
    session: AsyncSession,
    *,
    doctor: Doctor,
    patient: Patient,
    starts: Sequence[datetime],
    length: timedelta,
    attention_at: datetime | None = None,
) -> list[Appointment]:
    """Booked rows written directly: the booking service refuses past and off-grid times on purpose."""
    rows = [
        Appointment(
            patient_id=patient.id,
            doctor_id=doctor.id,
            start_time=start,
            end_time=start + length,
            status="booked",
            source="staff",
            staff_attention_reason="notification_failed" if attention_at else None,
            staff_attention_at=attention_at,
        )
        for start in starts
    ]
    session.add_all(rows)
    await session.flush()
    for row in rows:
        await session.refresh(row, ["ref"])  # assigned by the database sequence
    return rows


def describe_patient(patient: Patient) -> dict[str, Any]:
    return {"id": patient.id, "full_name": patient.full_name, "phone": patient.phone}


def describe_doctor(doctor: Doctor) -> dict[str, Any]:
    return {"id": doctor.id, "name": doctor.name, "specialty": doctor.specialty}


def describe_appointment(row: Appointment, tz: ZoneInfo) -> dict[str, Any]:
    local = row.start_time.astimezone(tz)
    return {
        "id": row.id,
        "reference": row.ref,
        "date": local.date().isoformat(),
        "start": row.start_time.astimezone(UTC).isoformat(),
        "time_label": format_time_12h(local),
    }
