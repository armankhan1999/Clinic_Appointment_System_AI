"""Slot generation and filtering (FR-03, E2-S2, E2-S4-AC3, GAP-09, GAP-14, GAP-35)."""

from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from clinic.domain.slots import (
    DateWindow,
    PartOfDay,
    ScheduleBlock,
    Slot,
    booking_window,
    day_slots,
    format_date_long,
    format_time_12h,
    free_slots,
    part_of_day,
)

IST = ZoneInfo("Asia/Kolkata")
MONDAY = date(2030, 1, 7)
BLOCKS = (
    ScheduleBlock(weekday=0, start=time(9), end=time(13), slot_minutes=15),
    ScheduleBlock(weekday=0, start=time(14), end=time(17), slot_minutes=15),
)
EARLY = datetime(2030, 1, 1, tzinfo=UTC)
WIDE = DateWindow(date(2030, 1, 1), date(2030, 12, 31))


def local(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=IST)


def starts(slots: Sequence[Slot]) -> list[str]:
    return [s.start.strftime("%H:%M") for s in slots]


def test_slots_follow_each_block_and_skip_the_lunch_break() -> None:
    slots = day_slots(BLOCKS, MONDAY, IST)
    assert len(slots) == 16 + 12
    assert starts(slots)[:2] == ["09:00", "09:15"]
    assert "12:45" in starts(slots)
    assert "13:00" not in starts(slots)
    assert "13:30" not in starts(slots)
    assert starts(slots)[-1] == "16:45"


def test_partial_slot_at_block_end_is_not_offered() -> None:
    block = ScheduleBlock(weekday=0, start=time(10), end=time(10, 50), slot_minutes=20)
    assert starts(day_slots([block], MONDAY, IST)) == ["10:00", "10:20"]


def test_no_slots_on_a_day_the_doctor_does_not_work() -> None:
    assert day_slots(BLOCKS, MONDAY + timedelta(days=1), IST) == []


def test_slots_are_timezone_aware_and_convert_to_utc() -> None:
    first = day_slots(BLOCKS, MONDAY, IST)[0]
    assert first.start.astimezone(UTC) == datetime(2030, 1, 7, 3, 30, tzinfo=UTC)
    assert first.end - first.start == timedelta(minutes=15)


def test_booked_interval_removes_every_overlapping_slot() -> None:
    busy = [(local(MONDAY, 10), local(MONDAY, 10, 20))]  # booked when slots were 20 minutes long
    result = free_slots(BLOCKS, MONDAY, IST, busy=busy, leave_days=set(), now=EARLY, window=WIDE)
    assert "10:00" not in starts(result)
    assert "10:15" not in starts(result)
    assert "09:45" in starts(result)
    assert "10:30" in starts(result)


def test_back_to_back_booking_does_not_block_the_next_slot() -> None:
    busy = [(local(MONDAY, 10), local(MONDAY, 10, 15))]
    result = free_slots(BLOCKS, MONDAY, IST, busy=busy, leave_days=set(), now=EARLY, window=WIDE)
    assert "10:15" in starts(result)


def test_leave_day_has_no_slots() -> None:
    assert free_slots(BLOCKS, MONDAY, IST, busy=[], leave_days={MONDAY}, now=EARLY, window=WIDE) == []


def test_only_slots_starting_after_now_are_offered() -> None:
    now = local(MONDAY, 10).astimezone(UTC)
    result = free_slots(BLOCKS, MONDAY, IST, busy=[], leave_days=set(), now=now, window=WIDE)
    assert starts(result)[0] == "10:15"


def test_days_outside_the_booking_window_have_no_slots() -> None:
    window = DateWindow(MONDAY + timedelta(days=1), MONDAY + timedelta(days=30))
    assert free_slots(BLOCKS, MONDAY, IST, busy=[], leave_days=set(), now=EARLY, window=window) == []


def test_booking_window_is_inclusive_in_the_clinic_time_zone() -> None:
    now = datetime(2030, 1, 6, 20, 0, tzinfo=UTC)  # already 7 January in India
    window = booking_window(now, IST, 30)
    assert (window.first, window.last) == (date(2030, 1, 7), date(2030, 2, 6))
    assert window.contains(date(2030, 2, 6))
    assert not window.contains(date(2030, 2, 7))
    assert not window.contains(date(2030, 1, 6))


@pytest.mark.parametrize(
    ("clock", "expected"),
    [
        (time(9), PartOfDay.MORNING),
        (time(11, 45), PartOfDay.MORNING),
        (time(12), PartOfDay.AFTERNOON),
        (time(16, 59), PartOfDay.AFTERNOON),
        (time(17), PartOfDay.EVENING),
    ],
)
def test_part_of_day_boundaries(clock: time, expected: PartOfDay) -> None:
    assert part_of_day(clock, morning_end=time(12), afternoon_end=time(17)) is expected


@pytest.mark.parametrize(
    ("clock", "label"),
    [(time(9), "9:00 AM"), (time(12), "12:00 PM"), (time(0, 15), "12:15 AM"), (time(13, 5), "1:05 PM")],
)
def test_twelve_hour_labels(clock: time, label: str) -> None:
    assert format_time_12h(datetime.combine(MONDAY, clock, tzinfo=IST)) == label


def test_long_date_label() -> None:
    assert format_date_long(date(2030, 1, 9)) == "Wednesday, 9 January 2030"
