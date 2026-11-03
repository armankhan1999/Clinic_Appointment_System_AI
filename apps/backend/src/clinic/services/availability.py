"""Doctor availability (FR-03, E2-S2, E2-S4-AC3, E2-S5-AC3, GAP-33).

One `DoctorCalendar` (schedule blocks, leave days, booked intervals over the booking window) is loaded per
request and evaluated with the pure functions in `clinic.domain.slots`. The booking service loads the same
calendar inside its own transaction to re-validate a slot before writing.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from clinic.db.models import Appointment, Doctor, DoctorLeave, DoctorSchedule
from clinic.domain.results import ResultCode
from clinic.domain.slots import (
    DateWindow,
    PartOfDay,
    ScheduleBlock,
    Slot,
    booking_window,
    free_slots,
    overlaps,
    part_of_day,
)
from clinic.services.clinic_settings import ClinicSettingsService, ClinicSettingsView


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class DoctorCalendar:
    doctor_id: UUID
    doctor_name: str
    blocks: tuple[ScheduleBlock, ...]
    leave_days: frozenset[date]
    busy: tuple[tuple[datetime, datetime], ...]

    def works_on(self, day: date) -> bool:
        return any(block.weekday == day.weekday() for block in self.blocks)

    def grid_on(self, day: date, tz: ZoneInfo, now: datetime, window: DateWindow) -> list[Slot]:
        """Bookable slots ignoring existing bookings: schedule, leave, window and now still apply."""
        return free_slots(
            self.blocks, day, tz, busy=(), leave_days=set(self.leave_days), now=now, window=window
        )

    def is_taken(self, slot: Slot) -> bool:
        return overlaps(slot, self.busy)

    def free_on(self, day: date, tz: ZoneInfo, now: datetime, window: DateWindow) -> list[Slot]:
        return free_slots(
            self.blocks, day, tz, busy=self.busy, leave_days=set(self.leave_days), now=now, window=window
        )

    def next_days_with_slots(
        self, after: date, tz: ZoneInfo, now: datetime, window: DateWindow, count: int
    ) -> tuple[date, ...]:
        found: list[date] = []
        day = after + timedelta(days=1)
        while day <= window.last and len(found) < count:
            if self.free_on(day, tz, now, window):
                found.append(day)
            day += timedelta(days=1)
        return tuple(found)


async def load_calendar(
    session: AsyncSession, doctor_id: UUID, window: DateWindow, tz: ZoneInfo
) -> DoctorCalendar | None:
    """None when the doctor does not exist or is inactive (E2-S1-AC2)."""
    doctor = await session.get(Doctor, doctor_id)
    if doctor is None or not doctor.active:
        return None
    schedule_query = select(DoctorSchedule).where(DoctorSchedule.doctor_id == doctor_id)
    schedules = (await session.scalars(schedule_query)).all()
    leaves = (
        await session.scalars(
            select(DoctorLeave.leave_date).where(
                DoctorLeave.doctor_id == doctor_id,
                DoctorLeave.leave_date.between(window.first, window.last),
            )
        )
    ).all()
    range_start = datetime.combine(window.first, time.min, tzinfo=tz)
    range_end = datetime.combine(window.last + timedelta(days=1), time.min, tzinfo=tz)
    booked = (
        await session.execute(
            select(Appointment.start_time, Appointment.end_time).where(
                Appointment.doctor_id == doctor_id,
                Appointment.status == "booked",
                Appointment.start_time < range_end,
                Appointment.end_time > range_start,
            )
        )
    ).all()
    return DoctorCalendar(
        doctor_id=doctor.id,
        doctor_name=doctor.name,
        blocks=tuple(ScheduleBlock(s.weekday, s.start_time, s.end_time, s.slot_minutes) for s in schedules),
        leave_days=frozenset(leaves),
        busy=tuple((row[0], row[1]) for row in booked),
    )


@dataclass(frozen=True)
class DayAvailability:
    code: ResultCode
    day: date
    doctor_name: str | None = None
    slots: tuple[Slot, ...] = ()
    next_dates: tuple[date, ...] = ()
    next_working_day: date | None = None
    other_parts: tuple[PartOfDay, ...] = ()


class AvailabilityService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        settings: ClinicSettingsService,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._clock = clock

    def now(self) -> datetime:
        return self._clock().astimezone(UTC)

    async def settings(self) -> ClinicSettingsView:
        return await self._settings.get()

    async def window(self) -> DateWindow:
        view = await self._settings.get()
        return booking_window(self.now(), view.tz, view.booking_window_days)

    async def day(self, doctor_id: UUID, day: date, part: PartOfDay | None = None) -> DayAvailability:
        view = await self._settings.get()
        now = self.now()
        window = booking_window(now, view.tz, view.booking_window_days)
        async with self._session_factory() as session:
            calendar = await load_calendar(session, doctor_id, window, view.tz)
        if calendar is None:
            return DayAvailability(ResultCode.NOT_FOUND, day)
        if not window.contains(day):
            return DayAvailability(ResultCode.INVALID_DATE, day, calendar.doctor_name)
        if not calendar.works_on(day):
            following = calendar.next_days_with_slots(day, view.tz, now, window, 1)
            return DayAvailability(
                ResultCode.DOCTOR_NOT_WORKING,
                day,
                calendar.doctor_name,
                next_working_day=following[0] if following else None,
            )

        def part_of(slot: Slot) -> PartOfDay:
            clock = slot.start.time()
            return part_of_day(clock, morning_end=view.morning_end, afternoon_end=view.afternoon_end)

        all_free = calendar.free_on(day, view.tz, now, window)
        selected = tuple(slot for slot in all_free if part is None or part_of(slot) is part)
        if selected:
            return DayAvailability(ResultCode.OK, day, calendar.doctor_name, slots=selected)
        other_parts = tuple(p for p in PartOfDay if p is not part and any(part_of(s) is p for s in all_free))
        return DayAvailability(
            ResultCode.NO_SLOTS,
            day,
            calendar.doctor_name,
            next_dates=calendar.next_days_with_slots(day, view.tz, now, window, 3),
            other_parts=other_parts,
        )
