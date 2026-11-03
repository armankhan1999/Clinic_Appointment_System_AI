"""Deterministic date phrases (E2-S5, GAP-15, GAP-36). The LLM passes the phrase; code decides the date.

Rules:
- `today`, `tomorrow`, `day after tomorrow`.
- `<weekday>` or `this <weekday>`: nearest occurrence on or after today.
- `next <weekday>`: first occurrence strictly after today.
- `YYYY-MM-DD`; `D Month [YYYY]`; `Month D [YYYY]` (a month/day already past this year means next year).
- A bare day of month (`the 5th`): this month if not yet past, else next month; in the last 7 days of a
  month it is ambiguous and the patient is asked which month (E2-S5-AC2).
- Numeric forms such as 13/01/2030 are rejected because D/M and M/D orders are both in use.
"""

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta

from clinic.domain.slots import MONTH_NAMES, WEEKDAY_NAMES

# Fixed English names: calendar.day_name / month_name follow the process locale.
WEEKDAYS = {name.lower(): index for index, name in enumerate(WEEKDAY_NAMES)}
MONTHS = {name.lower(): index for index, name in enumerate(MONTH_NAMES, start=1)}
MONTHS |= {name[:3]: index for name, index in list(MONTHS.items())} | {"sept": 9}
MONTH_END_AMBIGUITY_DAYS = 7

_ORDINAL = r"(\d{1,2})(?:st|nd|rd|th)?"
_WEEKDAY = re.compile(r"(this |next )?(" + "|".join(WEEKDAYS) + r")")
_ISO = re.compile(r"\d{4}-\d{2}-\d{2}")
_DAY_MONTH = re.compile(_ORDINAL + r" (?:of )?([a-z]+)(?:,? (\d{4}))?")
_MONTH_DAY = re.compile(r"([a-z]+) " + _ORDINAL + r"(?:,? (\d{4}))?")
_BARE_DAY = re.compile(_ORDINAL)


@dataclass(frozen=True)
class Resolved:
    day: date


@dataclass(frozen=True)
class Ambiguous:
    reason: str


@dataclass(frozen=True)
class Unrecognised:
    pass


type DateResolution = Resolved | Ambiguous | Unrecognised


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _month_and_day(month_name: str, day: int, year: str | None, today: date) -> DateResolution:
    month = MONTHS.get(month_name)
    if month is None:
        return Unrecognised()
    if year is not None:
        explicit = _safe_date(int(year), month, day)
        return Resolved(explicit) if explicit else Unrecognised()
    candidate = _safe_date(today.year, month, day)
    if candidate is None:
        return Unrecognised()
    if candidate < today:
        candidate = _safe_date(today.year + 1, month, day)
    return Resolved(candidate) if candidate else Unrecognised()


def _next_month(today: date) -> tuple[int, int]:
    return (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)


def _bare_day(day: int, today: date) -> DateResolution:
    if not 1 <= day <= 31:
        return Unrecognised()
    days_in_month = calendar.monthrange(today.year, today.month)[1]
    if today.day > days_in_month - MONTH_END_AMBIGUITY_DAYS:
        return Ambiguous("which month do you mean?")
    this_month = _safe_date(today.year, today.month, day) if day >= today.day else None
    if this_month is not None:
        return Resolved(this_month)
    year, month = _next_month(today)
    following = _safe_date(year, month, day)
    return Resolved(following) if following else Unrecognised()


def resolve_date(phrase: str, today: date) -> DateResolution:
    text = " ".join(phrase.strip().lower().rstrip(".!?").split())
    text = text.removeprefix("the ")
    if not text:
        return Unrecognised()
    relative = {"today": 0, "tomorrow": 1, "day after tomorrow": 2}
    if text in relative:
        return Resolved(today + timedelta(days=relative[text]))
    if match := _WEEKDAY.fullmatch(text):
        delta = (WEEKDAYS[match.group(2)] - today.weekday()) % 7
        if match.group(1) == "next " and delta == 0:
            delta = 7
        return Resolved(today + timedelta(days=delta))
    if _ISO.fullmatch(text):
        try:
            return Resolved(date.fromisoformat(text))
        except ValueError:
            return Unrecognised()
    if match := _DAY_MONTH.fullmatch(text):
        return _month_and_day(match.group(2), int(match.group(1)), match.group(3), today)
    if match := _MONTH_DAY.fullmatch(text):
        return _month_and_day(match.group(1), int(match.group(2)), match.group(3), today)
    if match := _BARE_DAY.fullmatch(text):
        return _bare_day(int(match.group(1)), today)
    return Unrecognised()
