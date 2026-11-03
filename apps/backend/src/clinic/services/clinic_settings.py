"""Clinic-wide settings (IMP-05), read through a short TTL cache."""

import time as clock_module
from collections.abc import Callable
from dataclasses import dataclass
from datetime import time
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from clinic.db.models import ClinicSettings


class ClinicSettingsMissingError(RuntimeError):
    """The clinic_settings row does not exist; run the seed or create it in the dashboard."""


@dataclass(frozen=True)
class ClinicSettingsView:
    clinic_name: str
    phone: str
    address: str
    staff_hours_text: str
    tz: ZoneInfo
    emergency_number: str
    emergency_phrases: tuple[str, ...]
    cutoff_minutes: int
    booking_window_days: int
    max_upcoming_per_patient: int
    max_per_doctor_per_day: int
    morning_end: time
    afternoon_end: time


class ClinicSettingsService:
    """Admin edits take effect within `ttl_seconds` (cache invalidation rule: time-based only)."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        ttl_seconds: float = 30.0,
        clock: Callable[[], float] = clock_module.monotonic,
    ) -> None:
        self._session_factory = session_factory
        self._ttl = ttl_seconds
        self._clock = clock
        self._cached: tuple[float, ClinicSettingsView] | None = None

    async def get(self) -> ClinicSettingsView:
        now = self._clock()
        if self._cached is not None and now - self._cached[0] < self._ttl:
            return self._cached[1]
        async with self._session_factory() as session:
            row = await session.get(ClinicSettings, 1)
        if row is None:
            raise ClinicSettingsMissingError("clinic_settings row 1 is missing")
        view = ClinicSettingsView(
            clinic_name=row.clinic_name,
            phone=row.phone,
            address=row.address,
            staff_hours_text=row.staff_hours_text,
            tz=ZoneInfo(row.timezone),
            emergency_number=row.emergency_number,
            emergency_phrases=tuple(row.emergency_phrases),
            cutoff_minutes=row.cutoff_minutes,
            booking_window_days=row.booking_window_days,
            max_upcoming_per_patient=row.max_upcoming_per_patient,
            max_per_doctor_per_day=row.max_per_doctor_per_day,
            morning_end=row.morning_end,
            afternoon_end=row.afternoon_end,
        )
        self._cached = (now, view)
        return view
