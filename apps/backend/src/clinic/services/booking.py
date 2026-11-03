"""Booking (FR-04, FR-05, BR-03, E2-S3, E2-S4).

`precheck` is read-only (used when the agent stages a booking, E2-S3-AC1). `book` runs in one transaction:
lock the patient row (serialises one patient's parallel taps for the limits, E7-S4-AC2), re-validate the
slot, leave, window and limits (MP-04), insert, and let the database's partial unique index and exclusion
constraint settle any race between patients (E2-S4-AC1).
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from clinic.db.models import Appointment, Patient
from clinic.domain.results import ResultCode
from clinic.domain.slots import DateWindow, Slot, booking_window
from clinic.services.audit import ActorType, AuditService
from clinic.services.availability import DoctorCalendar, load_calendar, utc_now
from clinic.services.clinic_settings import ClinicSettingsService, ClinicSettingsView

type BookingSource = Literal["bot", "staff"]
type LimitReason = Literal["same_doctor_same_day", "max_upcoming"]

DOUBLE_BOOKING_CONSTRAINTS = frozenset({"ux_appt_doctor_start_booked", "ex_appt_no_overlap"})
ALTERNATIVES = 3  # GAP-34


@dataclass(frozen=True)
class BookingCheck:
    code: ResultCode
    doctor_name: str | None = None
    slot: Slot | None = None
    reason: LimitReason | None = None


@dataclass(frozen=True)
class BookingOutcome:
    code: ResultCode
    doctor_name: str | None = None
    slot: Slot | None = None
    reference: str | None = None
    appointment_id: UUID | None = None
    reason: LimitReason | None = None
    alternatives: tuple[Slot, ...] = ()


def nearest_free_slots(
    calendar: DoctorCalendar, around: datetime, tz: ZoneInfo, now: datetime, window: DateWindow, count: int
) -> tuple[Slot, ...]:
    """Closest free slots to `around` for the same doctor (ties: earlier first), returned in time order."""
    day = around.astimezone(tz).date()
    candidates = calendar.free_on(day, tz, now, window)
    following = day + timedelta(days=1)
    while following <= window.last and sum(1 for slot in candidates if slot.start > around) < count:
        candidates += calendar.free_on(following, tz, now, window)
        following += timedelta(days=1)
    chosen = sorted(candidates, key=lambda slot: (abs(slot.start - around), slot.start))[:count]
    return tuple(sorted(chosen, key=lambda slot: slot.start))


def _constraint_name(exc: IntegrityError) -> str | None:
    driver_error = exc.orig.__cause__ if exc.orig is not None else None
    name = getattr(driver_error, "constraint_name", None)
    return name if isinstance(name, str) else None


def _day_bounds(moment: datetime, tz: ZoneInfo) -> tuple[datetime, datetime]:
    day = moment.astimezone(tz).date()
    start = datetime.combine(day, time.min, tzinfo=tz)
    return start, start + timedelta(days=1)


class BookingService:
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

    def _now(self) -> datetime:
        return self._clock().astimezone(UTC)

    async def precheck(
        self,
        patient_id: UUID,
        doctor_id: UUID,
        slot_start: datetime,
        *,
        exclude_appointment_id: UUID | None = None,
    ) -> BookingCheck:
        view = await self._settings.get()
        now = self._now()
        async with self._session_factory() as session:
            check, _ = await self._check(
                session, view, now, patient_id, doctor_id, slot_start, exclude_appointment_id
            )
        return check

    async def _check(
        self,
        session: AsyncSession,
        view: ClinicSettingsView,
        now: datetime,
        patient_id: UUID,
        doctor_id: UUID,
        slot_start: datetime,
        exclude_appointment_id: UUID | None,
    ) -> tuple[BookingCheck, DoctorCalendar | None]:
        window = booking_window(now, view.tz, view.booking_window_days)
        calendar = await load_calendar(session, doctor_id, window, view.tz)
        if calendar is None:
            return BookingCheck(ResultCode.NOT_FOUND), None
        day = slot_start.astimezone(view.tz).date()
        slot = next((s for s in calendar.grid_on(day, view.tz, now, window) if s.start == slot_start), None)
        if slot is None:  # never bookable: off-grid, past, leave or outside the window
            return BookingCheck(ResultCode.SLOT_UNAVAILABLE, calendar.doctor_name), calendar
        if calendar.is_taken(slot):  # E2-S3-AC3: someone else got it first
            return BookingCheck(ResultCode.SLOT_TAKEN, calendar.doctor_name, slot), calendar
        mine: list[ColumnElement[bool]] = [
            Appointment.patient_id == patient_id,
            Appointment.status == "booked",
        ]
        if (
            exclude_appointment_id is not None
        ):  # a reschedule does not count the appointment it moves (GAP-20)
            mine.append(Appointment.id != exclude_appointment_id)
        upcoming = await session.scalar(
            select(func.count()).select_from(Appointment).where(*mine, Appointment.start_time > now)
        )
        if (upcoming or 0) >= view.max_upcoming_per_patient:
            return BookingCheck(
                ResultCode.LIMIT_REACHED, calendar.doctor_name, slot, "max_upcoming"
            ), calendar
        day_start, day_end = _day_bounds(slot_start, view.tz)
        same_day = await session.scalar(
            select(func.count())
            .select_from(Appointment)
            .where(
                *mine,
                Appointment.doctor_id == doctor_id,
                Appointment.start_time >= day_start,
                Appointment.start_time < day_end,
            )
        )
        if (same_day or 0) >= view.max_per_doctor_per_day:
            return BookingCheck(
                ResultCode.LIMIT_REACHED, calendar.doctor_name, slot, "same_doctor_same_day"
            ), calendar
        return BookingCheck(ResultCode.OK, calendar.doctor_name, slot), calendar

    async def book(
        self,
        *,
        patient_id: UUID,
        doctor_id: UUID,
        slot_start: datetime,
        source: BookingSource,
        actor_type: ActorType = "patient_button",
        staff_user_id: UUID | None = None,
    ) -> BookingOutcome:
        view = await self._settings.get()
        now = self._now()
        audit_args = {
            "doctor_id": str(doctor_id),
            "slot_start": slot_start.astimezone(UTC).isoformat(),
            "source": source,
        }
        actor_id = str(staff_user_id) if staff_user_id else None
        try:
            async with self._session_factory() as session, session.begin():
                patient = await session.scalar(
                    select(Patient)
                    .where(Patient.id == patient_id, Patient.deleted_at.is_(None))
                    .with_for_update()
                )
                if patient is None:
                    return BookingOutcome(ResultCode.NOT_FOUND)
                check, _ = await self._check(session, view, now, patient_id, doctor_id, slot_start, None)
                if check.code is not ResultCode.SLOT_TAKEN:
                    if check.code is not ResultCode.OK or check.slot is None:
                        self._audit(session, actor_type, actor_id, audit_args, check.code, patient_id)
                        return BookingOutcome(check.code, check.doctor_name, check.slot, reason=check.reason)
                    appointment = Appointment(
                        patient_id=patient_id,
                        doctor_id=doctor_id,
                        start_time=check.slot.start,
                        end_time=check.slot.end,
                        status="booked",
                        source=source,
                        created_by_staff_id=staff_user_id,
                    )
                    session.add(appointment)
                    await session.flush()  # the double-booking constraints fire here
                    self._audit(session, actor_type, actor_id, audit_args, ResultCode.OK, patient_id)
                    return BookingOutcome(
                        ResultCode.OK,
                        check.doctor_name,
                        check.slot,
                        reference=appointment.ref,
                        appointment_id=appointment.id,
                    )
        except IntegrityError as exc:
            if _constraint_name(exc) not in DOUBLE_BOOKING_CONSTRAINTS:
                raise
        return await self._slot_taken(
            view, now, patient_id, doctor_id, slot_start, actor_type, actor_id, audit_args
        )

    async def _slot_taken(
        self,
        view: ClinicSettingsView,
        now: datetime,
        patient_id: UUID,
        doctor_id: UUID,
        slot_start: datetime,
        actor_type: ActorType,
        actor_id: str | None,
        audit_args: dict[str, str],
    ) -> BookingOutcome:
        window = booking_window(now, view.tz, view.booking_window_days)
        async with self._session_factory() as session, session.begin():
            self._audit(session, actor_type, actor_id, audit_args, ResultCode.SLOT_TAKEN, patient_id)
            calendar = await load_calendar(session, doctor_id, window, view.tz)
        if calendar is None:
            return BookingOutcome(ResultCode.SLOT_TAKEN)
        alternatives = nearest_free_slots(calendar, slot_start, view.tz, now, window, ALTERNATIVES)
        return BookingOutcome(ResultCode.SLOT_TAKEN, calendar.doctor_name, alternatives=alternatives)

    @staticmethod
    def _audit(
        session: AsyncSession,
        actor_type: ActorType,
        actor_id: str | None,
        args: dict[str, str],
        result: ResultCode,
        patient_id: UUID,
    ) -> None:
        AuditService.record(
            session,
            actor_type=actor_type,
            actor_id=actor_id,
            action="appointment.book",
            args=args,
            result=result,
            patient_id=patient_id,
            latency_ms=None,
        )
