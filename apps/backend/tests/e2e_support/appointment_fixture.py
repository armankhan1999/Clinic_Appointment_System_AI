"""Booked appointments for one new synthetic patient, including times the staff API refuses to book.

    uv run python -m tests.e2e_support.appointment_fixture --minutes-from-now -90 --count 2
    uv run python -m tests.e2e_support.appointment_fixture --day 2026-12-21 --time 10:00 --doctor-id <uuid>
    uv run python -m tests.e2e_support.appointment_fixture --count 0          # the patient only

Attendance can only be marked after the start (E6-S5) and POST /appointments refuses past slots, so the
rows are written directly. The `count` appointments are back to back with the first active doctor (by
name) unless --doctor-id is given. A block that overlaps a booked appointment of that doctor moves by one
appointment length: earlier for past times, later otherwise. Prints
{"patient": {...}, "doctor": {...}, "appointments": [{id, reference, date, start, time_label}]}.
"""

import argparse
import sys
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from clinic.services.clinic_settings import ClinicSettingsService
from tests.e2e_support.common import (
    Fixture,
    FixtureError,
    active_doctor,
    add_appointments,
    booked_ranges,
    describe_appointment,
    describe_doctor,
    describe_patient,
    first_free_start,
    new_patient,
    run,
)


def _arguments(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    when = parser.add_mutually_exclusive_group()
    when.add_argument("--minutes-from-now", type=int, help="start of the first appointment, negative = past")
    when.add_argument("--day", type=date.fromisoformat, help="clinic-time day (YYYY-MM-DD), with --time")
    parser.add_argument("--time", type=time.fromisoformat, default=time(10), help="clinic-time HH:MM")
    parser.add_argument("--count", type=int, default=1, choices=range(6))
    parser.add_argument("--length", type=int, default=15, help="minutes per appointment")
    parser.add_argument("--doctor-id", type=UUID)
    parser.add_argument("--label", default="Patient", help="middle word of the patient's name")
    args = parser.parse_args(argv)
    if args.count > 0 and args.minutes_from_now is None and args.day is None:
        parser.error("give --minutes-from-now or --day for the appointments")
    return args


def fixture(args: argparse.Namespace) -> Fixture:
    async def create(session_factory: async_sessionmaker[AsyncSession]) -> dict[str, Any]:
        tz = (await ClinicSettingsService(session_factory).get()).tz
        now = datetime.now(UTC).replace(second=0, microsecond=0)
        length = timedelta(minutes=args.length)
        async with session_factory() as session, session.begin():
            patient = await new_patient(session, args.label, now)
            result: dict[str, Any] = {"patient": describe_patient(patient), "appointments": []}
            if args.count == 0:
                return result
            doctor = await active_doctor(session, args.doctor_id)
            if args.day is not None:
                wanted = datetime.combine(args.day, args.time, tzinfo=tz)
                step = length
            else:
                wanted = now + timedelta(minutes=args.minutes_from_now)
                step = -length if args.minutes_from_now < 0 else length
            block = length * args.count
            first = first_free_start(wanted, block, await booked_ranges(session, doctor.id, wanted), step)
            if (
                args.day is not None
                and (first + block - timedelta(minutes=1)).astimezone(tz).date() != args.day
            ):
                raise FixtureError(f"no free {block} left on {args.day} for {doctor.name}")
            if args.minutes_from_now is not None and args.minutes_from_now < 0 and first + block > now:
                raise FixtureError("the appointments would not all have started yet")
            rows = await add_appointments(
                session,
                doctor=doctor,
                patient=patient,
                starts=[first + length * index for index in range(args.count)],
                length=length,
            )
            result["doctor"] = describe_doctor(doctor)
            result["appointments"] = [describe_appointment(row, tz) for row in rows]
            return result

    return create


if __name__ == "__main__":
    sys.exit(run(fixture(_arguments(sys.argv[1:]))))
