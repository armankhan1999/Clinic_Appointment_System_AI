"""Appointment slots from weekly schedules (FR-03, GAP-09, GAP-14, GAP-35). Pure functions, no I/O."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

WEEKDAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
MONTH_NAMES = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)  # fmt: skip


@dataclass(frozen=True)
class ScheduleBlock:
    weekday: int  # 0 = Monday
    start: time
    end: time
    slot_minutes: int


@dataclass(frozen=True)
class Slot:
    start: datetime  # aware, clinic time zone
    end: datetime


@dataclass(frozen=True)
class DateWindow:
    first: date
    last: date

    def contains(self, day: date) -> bool:
        return self.first <= day <= self.last


class PartOfDay(StrEnum):
    MORNING = "morning"
    AFTERNOON = "afternoon"
    EVENING = "evening"


def booking_window(now: datetime, tz: ZoneInfo, days: int) -> DateWindow:
    """Today through today + `days`, inclusive, in the clinic time zone."""
    today = now.astimezone(tz).date()
    return DateWindow(today, today + timedelta(days=days))


def day_slots(blocks: Iterable[ScheduleBlock], day: date, tz: ZoneInfo) -> list[Slot]:
    """Every whole slot in the doctor's blocks for that weekday; a partial slot at a block end is dropped."""
    slots: list[Slot] = []
    for block in sorted((b for b in blocks if b.weekday == day.weekday()), key=lambda b: b.start):
        step = timedelta(minutes=block.slot_minutes)
        cursor = datetime.combine(day, block.start, tzinfo=tz)
        block_end = datetime.combine(day, block.end, tzinfo=tz)
        while cursor + step <= block_end:
            slots.append(Slot(cursor, cursor + step))
            cursor += step
    return slots


def overlaps(slot: Slot, busy: Sequence[tuple[datetime, datetime]]) -> bool:
    return any(start < slot.end and slot.start < end for start, end in busy)


def free_slots(
    blocks: Iterable[ScheduleBlock],
    day: date,
    tz: ZoneInfo,
    *,
    busy: Sequence[tuple[datetime, datetime]],
    leave_days: set[date],
    now: datetime,
    window: DateWindow,
) -> list[Slot]:
    """Schedule minus leave (E2-S4-AC3), booked intervals, past starts and days outside the window."""
    if not window.contains(day) or day in leave_days:
        return []
    return [slot for slot in day_slots(blocks, day, tz) if slot.start > now and not overlaps(slot, busy)]


def part_of_day(clock: time, *, morning_end: time, afternoon_end: time) -> PartOfDay:
    if clock < morning_end:
        return PartOfDay.MORNING
    if clock < afternoon_end:
        return PartOfDay.AFTERNOON
    return PartOfDay.EVENING


def format_time_12h(moment: datetime) -> str:
    hour = moment.hour % 12 or 12
    return f"{hour}:{moment.minute:02d} {'AM' if moment.hour < 12 else 'PM'}"


def format_date_long(day: date) -> str:
    return f"{WEEKDAY_NAMES[day.weekday()]}, {day.day} {MONTH_NAMES[day.month - 1]} {day.year}"
