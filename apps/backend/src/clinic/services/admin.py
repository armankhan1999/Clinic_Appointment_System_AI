"""Administration behind the staff API (IMP-01..05, E6-S3, E6-S6, E7-S2-AC3). Every write is audited."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from itertools import pairwise
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import TypeAdapter
from sqlalchemy import ColumnElement, Select, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import InstrumentedAttribute

from clinic.db.models import (
    Appointment,
    AuditLog,
    ClinicInfo,
    ClinicSettings,
    Doctor,
    DoctorLeave,
    DoctorSchedule,
    Notification,
    Patient,
    StaffSession,
    StaffUser,
)
from clinic.domain.results import ResultCode
from clinic.services.audit import AuditService
from clinic.services.availability import utc_now
from clinic.services.booking import constraint_name
from clinic.services.clinic_settings import ClinicSettingsService
from clinic.services.staff_auth import (
    InvalidUsernameError,
    Role,
    StaffAuthService,
    StaffPrincipal,
    WeakPasswordError,
    hash_password,
)
from clinic.services.staff_ops import AppointmentOut, OperationRefusedError, appointment_rows

SETTINGS_FIELDS = (
    "clinic_name",
    "phone",
    "address",
    "staff_hours_text",
    "timezone",
    "emergency_number",
    "emergency_phrases",
    "cutoff_minutes",
    "booking_window_days",
    "max_upcoming_per_patient",
    "max_per_doctor_per_day",
    "morning_end",
    "afternoon_end",
)

_APPOINTMENTS = TypeAdapter(list[AppointmentOut])  # 409 details carry the same shape as the preview


async def _page[M](
    session: AsyncSession,
    query: Select[M],
    order: tuple[ColumnElement[Any] | InstrumentedAttribute[Any], ...],
    page: int,
    page_size: int,
) -> tuple[list[M], int]:
    """One page of `query` plus the total row count (docs/api/staff-api.md: lists are paginated)."""
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = await session.scalars(query.order_by(*order).offset((page - 1) * page_size).limit(page_size))
    return list(rows.all()), int(total or 0)


@dataclass(frozen=True)
class Block:
    weekday: int
    start: time
    end: time
    slot_minutes: int


@dataclass(frozen=True)
class DoctorOut:
    id: UUID
    name: str
    specialty: str
    active: bool


@dataclass(frozen=True)
class StaffUserOut:
    id: UUID
    username: str
    display_name: str
    role: str
    active: bool
    locked_until: datetime | None


def _refuse(message: str, **details: Any) -> OperationRefusedError:
    return OperationRefusedError(ResultCode.VALIDATION_ERROR, message, details)


def validate_blocks(blocks: Sequence[Block]) -> None:
    """E6-S3-AC2: end after start, slot length 5-120 minutes, no overlapping blocks on one weekday."""
    for block in blocks:
        if not 0 <= block.weekday <= 6:
            raise _refuse("Weekday must be 0 (Monday) to 6 (Sunday).")
        if block.end <= block.start:
            raise _refuse("Each block must end after it starts.", weekday=block.weekday)
        if not 5 <= block.slot_minutes <= 120:
            raise _refuse("Slot length must be between 5 and 120 minutes.", weekday=block.weekday)
    for weekday in range(7):
        day = sorted((b for b in blocks if b.weekday == weekday), key=lambda b: b.start)
        for earlier, later in pairwise(day):
            if later.start < earlier.end:
                raise _refuse("Blocks on the same day must not overlap.", weekday=weekday)


class AdminService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        settings: ClinicSettingsService,
        auth: StaffAuthService,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._auth = auth
        self._clock = clock

    # ---- doctors and schedules (IMP-01, E6-S3) -----------------------------------------------------

    async def create_doctor(self, principal: StaffPrincipal, name: str, specialty: str) -> DoctorOut:
        async with self._session_factory() as session, session.begin():
            doctor = Doctor(name=name.strip(), specialty=specialty.strip())
            session.add(doctor)
            await session.flush()
            self._audit(session, principal, "doctor.create", {"doctor_id": str(doctor.id)})
            return DoctorOut(doctor.id, doctor.name, doctor.specialty, doctor.active)

    async def update_doctor(
        self, principal: StaffPrincipal, doctor_id: UUID, changes: dict[str, Any]
    ) -> DoctorOut:
        async with self._session_factory() as session, session.begin():
            doctor = await session.get(Doctor, doctor_id, with_for_update=True)
            if doctor is None:
                raise OperationRefusedError(ResultCode.NOT_FOUND, "Doctor not found.")
            for key in ("name", "specialty", "active"):
                if key in changes and changes[key] is not None:
                    setattr(
                        doctor, key, changes[key].strip() if isinstance(changes[key], str) else changes[key]
                    )
            self._audit(
                session, principal, "doctor.update", {"doctor_id": str(doctor.id), "fields": sorted(changes)}
            )
            return DoctorOut(doctor.id, doctor.name, doctor.specialty, doctor.active)

    async def schedule(self, doctor_id: UUID) -> list[Block]:
        async with self._session_factory() as session:
            if await session.get(Doctor, doctor_id) is None:
                raise OperationRefusedError(ResultCode.NOT_FOUND, "Doctor not found.")
            rows = (
                await session.scalars(
                    select(DoctorSchedule)
                    .where(DoctorSchedule.doctor_id == doctor_id)
                    .order_by(DoctorSchedule.weekday, DoctorSchedule.start_time)
                )
            ).all()
        return [Block(r.weekday, r.start_time, r.end_time, r.slot_minutes) for r in rows]

    async def replace_schedule(
        self, principal: StaffPrincipal, doctor_id: UUID, blocks: list[Block]
    ) -> list[Block]:
        validate_blocks(blocks)
        async with self._session_factory() as session, session.begin():
            # The doctor row lock serialises concurrent edits of one doctor's week (GAP-09).
            if await session.get(Doctor, doctor_id, with_for_update=True) is None:
                raise OperationRefusedError(ResultCode.NOT_FOUND, "Doctor not found.")
            for row in (
                await session.scalars(select(DoctorSchedule).where(DoctorSchedule.doctor_id == doctor_id))
            ).all():
                await session.delete(row)
            await session.flush()
            session.add_all(
                DoctorSchedule(
                    doctor_id=doctor_id,
                    weekday=b.weekday,
                    start_time=b.start,
                    end_time=b.end,
                    slot_minutes=b.slot_minutes,
                )
                for b in blocks
            )
            self._audit(
                session, principal, "doctor.schedule", {"doctor_id": str(doctor_id), "blocks": len(blocks)}
            )
        return await self.schedule(doctor_id)

    async def leaves(self, doctor_id: UUID) -> list[dict[str, Any]]:
        async with self._session_factory() as session:
            rows = (
                await session.scalars(
                    select(DoctorLeave)
                    .where(DoctorLeave.doctor_id == doctor_id)
                    .order_by(DoctorLeave.leave_date)
                )
            ).all()
        return [{"id": r.id, "date": r.leave_date, "reason": r.reason} for r in rows]

    async def _booked_on(self, session: AsyncSession, doctor_id: UUID, day: date) -> list[Appointment]:
        view = await self._settings.get()
        start = datetime.combine(day, time.min, tzinfo=view.tz)
        return list(
            (
                await session.scalars(
                    select(Appointment)
                    .where(
                        Appointment.doctor_id == doctor_id,
                        Appointment.status == "booked",
                        Appointment.start_time >= start,
                        Appointment.start_time < start + timedelta(days=1),
                    )
                    .order_by(Appointment.start_time)
                    .with_for_update()
                )
            ).all()
        )

    async def preview_leave(self, doctor_id: UUID, day: date) -> list[AppointmentOut]:
        view = await self._settings.get()
        async with self._session_factory() as session:
            return await appointment_rows(
                session, await self._booked_on(session, doctor_id, day), view, self._clock()
            )

    async def create_leave(
        self, principal: StaffPrincipal, doctor_id: UUID, day: date, reason: str, confirm_affected: bool
    ) -> tuple[dict[str, Any], list[AppointmentOut]]:
        """E6-S3-AC3: affected bookings are listed first; once confirmed they are cancelled and notified."""
        view = await self._settings.get()
        now = self._clock()
        async with self._session_factory() as session, session.begin():
            if await session.get(Doctor, doctor_id, with_for_update=True) is None:
                raise OperationRefusedError(ResultCode.NOT_FOUND, "Doctor not found.")
            affected = await self._booked_on(session, doctor_id, day)
            if affected and not confirm_affected:
                rows = await appointment_rows(session, affected, view, now)
                raise OperationRefusedError(
                    "CONFLICT",
                    f"{len(rows)} booked appointment(s) fall on that day. "
                    "Confirm to cancel them and notify patients.",
                    {"affected": _APPOINTMENTS.dump_python(rows, mode="json")},
                )
            if await session.scalar(
                select(DoctorLeave.id).where(
                    DoctorLeave.doctor_id == doctor_id, DoctorLeave.leave_date == day
                )
            ):
                raise OperationRefusedError("CONFLICT", "Leave is already recorded for that day.")
            leave = DoctorLeave(
                doctor_id=doctor_id, leave_date=day, reason=reason, created_by=principal.user_id
            )
            session.add(leave)
            patients = {
                p.id: p
                for p in (
                    await session.scalars(
                        select(Patient).where(Patient.id.in_({a.patient_id for a in affected}))
                    )
                ).all()
            }
            for appointment in affected:
                appointment.status = "cancelled"
                appointment.cancelled_at = now
                appointment.cancelled_by_kind = "staff"
                appointment.cancel_reason = reason
                patient = patients[appointment.patient_id]
                if patient.telegram_user_id is not None and patient.deleted_at is None:
                    session.add(
                        Notification(
                            appointment_id=appointment.id,
                            patient_id=patient.id,
                            kind="doctor_leave",
                            reason=reason,
                            next_attempt_at=now,
                        )
                    )
            await session.flush()
            self._audit(
                session, principal, "doctor.leave", {"doctor_id": str(doctor_id), "cancelled": len(affected)}
            )
            cancelled = await appointment_rows(session, affected, view, now)
            return {"id": leave.id, "date": leave.leave_date, "reason": leave.reason}, cancelled

    async def delete_leave(self, principal: StaffPrincipal, doctor_id: UUID, leave_id: UUID) -> None:
        async with self._session_factory() as session, session.begin():
            leave = await session.get(DoctorLeave, leave_id)
            if leave is None or leave.doctor_id != doctor_id:
                raise OperationRefusedError(ResultCode.NOT_FOUND, "Leave not found.")
            await session.delete(leave)
            self._audit(session, principal, "doctor.leave_delete", {"doctor_id": str(doctor_id)})

    # ---- FAQ (IMP-02) ------------------------------------------------------------------------------

    async def faq(self, page: int, page_size: int) -> tuple[list[ClinicInfo], int]:
        async with self._session_factory() as session:
            return await _page(session, select(ClinicInfo), (ClinicInfo.topic,), page, page_size)

    async def save_faq(
        self, principal: StaffPrincipal, entry_id: UUID | None, changes: dict[str, Any]
    ) -> ClinicInfo:
        topic_taken = OperationRefusedError("CONFLICT", "Another entry already uses that topic.")
        async with self._session_factory() as session, session.begin():
            if changes.get("topic") is not None:
                clash = select(ClinicInfo.id).where(ClinicInfo.topic == changes["topic"])
                if entry_id is not None:
                    clash = clash.where(ClinicInfo.id != entry_id)
                if await session.scalar(clash) is not None:
                    raise topic_taken
            if entry_id is None:
                entry = ClinicInfo(updated_by=principal.user_id, **changes)
                session.add(entry)
            else:
                found = await session.get(ClinicInfo, entry_id, with_for_update=True)
                if found is None:
                    raise OperationRefusedError(ResultCode.NOT_FOUND, "FAQ entry not found.")
                entry = found
                for key, value in changes.items():
                    setattr(entry, key, value)
                entry.updated_by = principal.user_id
            try:
                await session.flush()
            except IntegrityError as exc:  # a concurrent save took the topic after the check above
                if constraint_name(exc) != "uq_clinic_info_topic":
                    raise
                raise topic_taken from exc
            await session.refresh(entry)
            self._audit(session, principal, "faq.save", {"topic": entry.topic})
            return entry

    async def delete_faq(self, principal: StaffPrincipal, entry_id: UUID) -> None:
        async with self._session_factory() as session, session.begin():
            entry = await session.get(ClinicInfo, entry_id)
            if entry is None:
                raise OperationRefusedError(ResultCode.NOT_FOUND, "FAQ entry not found.")
            await session.delete(entry)
            self._audit(session, principal, "faq.delete", {"topic": entry.topic})

    # ---- settings (IMP-05) ---------------------------------------------------------------------------

    async def get_settings(self) -> dict[str, Any]:
        async with self._session_factory() as session:
            row = await session.get(ClinicSettings, 1)
        if row is None:
            raise OperationRefusedError(ResultCode.NOT_FOUND, "Clinic settings are missing; run the seed.")
        return {name: getattr(row, name) for name in SETTINGS_FIELDS}

    async def update_settings(self, principal: StaffPrincipal, changes: dict[str, Any]) -> dict[str, Any]:
        async with self._session_factory() as session, session.begin():
            row = await session.get(ClinicSettings, 1, with_for_update=True)
            if row is None:
                raise OperationRefusedError(
                    ResultCode.NOT_FOUND, "Clinic settings are missing; run the seed."
                )
            merged = {name: changes.get(name, getattr(row, name)) for name in SETTINGS_FIELDS}
            try:
                ZoneInfo(merged["timezone"])
            except (ZoneInfoNotFoundError, ValueError) as exc:
                raise _refuse("Unknown time zone.", fields=["timezone"]) from exc
            if merged["morning_end"] >= merged["afternoon_end"]:
                raise _refuse(
                    "Morning must end before the afternoon ends.", fields=["morning_end", "afternoon_end"]
                )
            for name, value in changes.items():
                setattr(row, name, value)
            row.updated_by = principal.user_id
            self._audit(session, principal, "settings.update", {"fields": sorted(changes)})
        return await self.get_settings()

    # ---- audit viewer (E7-S2-AC3, IMP-03) ------------------------------------------------------------

    async def audit(
        self, filters: dict[str, Any], page: int, page_size: int
    ) -> tuple[list[dict[str, Any]], int]:
        """`from` and `to` are whole days in the clinic time zone, both inclusive."""
        view = await self._settings.get()
        query = select(AuditLog)
        if filters.get("from"):
            query = query.where(AuditLog.ts >= datetime.combine(filters["from"], time.min, tzinfo=view.tz))
        if filters.get("to"):
            day_after = filters["to"] + timedelta(days=1)
            query = query.where(AuditLog.ts < datetime.combine(day_after, time.min, tzinfo=view.tz))
        for name in ("actor_type", "action", "patient_id"):
            if filters.get(name) is not None:
                query = query.where(getattr(AuditLog, name) == filters[name])
        async with self._session_factory() as session:
            rows, total = await _page(
                session, query, (AuditLog.ts.desc(), AuditLog.id.desc()), page, page_size
            )
        items = [
            {
                "id": r.id,
                "ts": r.ts,
                "actor_type": r.actor_type,
                "actor_id": r.actor_id,
                "patient_id": r.patient_id,
                "action": r.action,
                "args": r.args_json,
                "result": r.result,
                "latency_ms": r.latency_ms,
                "request_id": r.request_id,
            }
            for r in rows
        ]
        return items, total

    # ---- weekly metrics (E6-S6, GAP-24) --------------------------------------------------------------

    async def weekly_metrics(self, week_start: date) -> dict[str, Any]:
        """Appointments starting in the week (clinic time): source, cancellations, no-show rate per doctor.

        no_show_rate = no_show / (completed + no_show), and 0 when nobody attended or missed (E6-S6-AC2).
        """
        view = await self._settings.get()
        start = datetime.combine(week_start, time.min, tzinfo=view.tz)
        end = start + timedelta(days=7)
        async with self._session_factory() as session:
            doctors = (await session.scalars(select(Doctor).order_by(Doctor.name))).all()
            appointments = (
                await session.scalars(
                    select(Appointment).where(Appointment.start_time >= start, Appointment.start_time < end)
                )
            ).all()
        by_source = {"bot": 0, "staff": 0}
        cancellations = 0
        for a in appointments:
            by_source[a.source] = by_source.get(a.source, 0) + 1
            cancellations += a.status == "cancelled"
        per_doctor = []
        for d in doctors:
            completed = sum(1 for a in appointments if a.doctor_id == d.id and a.status == "completed")
            no_show = sum(1 for a in appointments if a.doctor_id == d.id and a.status == "no_show")
            seen = completed + no_show
            per_doctor.append(
                {
                    "doctor_id": d.id,
                    "name": d.name,
                    "completed": completed,
                    "no_show": no_show,
                    "no_show_rate": round(no_show / seen, 4) if seen else 0,
                }
            )
        return {
            "week_start": week_start,
            "bookings_by_source": by_source,
            "cancellations": cancellations,
            "per_doctor": per_doctor,
        }

    # ---- staff users (IMP-04) --------------------------------------------------------------------------

    async def staff_users(self, page: int, page_size: int) -> tuple[list[StaffUserOut], int]:
        async with self._session_factory() as session:
            rows, total = await _page(session, select(StaffUser), (StaffUser.username,), page, page_size)
        users = [
            StaffUserOut(u.id, u.username, u.display_name, u.role, u.active, u.locked_until) for u in rows
        ]
        return users, total

    async def create_staff_user(
        self, principal: StaffPrincipal, username: str, display_name: str, role: Role, password: str
    ) -> StaffUserOut:
        try:
            user = await self._auth.create_user(
                username=username,
                display_name=display_name,
                role=role,
                password=password,
                actor_id=principal.user_id,
            )
        except (WeakPasswordError, InvalidUsernameError) as exc:
            raise _refuse(str(exc)) from exc
        except IntegrityError as exc:
            if constraint_name(exc) != "ux_staff_users_username_lower":
                raise
            raise OperationRefusedError("CONFLICT", "That username is already taken.") from exc
        return StaffUserOut(user.id, user.username, user.display_name, user.role, user.active, None)

    async def update_staff_user(
        self, principal: StaffPrincipal, user_id: UUID, changes: dict[str, Any]
    ) -> StaffUserOut:
        new_hash = None
        if changes.get("password"):
            try:
                new_hash = await hash_password(changes["password"])
            except WeakPasswordError as exc:
                raise _refuse(str(exc)) from exc
        async with self._session_factory() as session, session.begin():
            user = await session.get(StaffUser, user_id, with_for_update=True)
            if user is None:
                raise OperationRefusedError(ResultCode.NOT_FOUND, "Staff user not found.")
            if user.id == principal.user_id and (
                changes.get("active") is False or changes.get("role") == "receptionist"
            ):
                raise OperationRefusedError("CONFLICT", "You cannot deactivate or demote your own account.")
            for key in ("display_name", "role", "active"):
                if changes.get(key) is not None:
                    setattr(user, key, changes[key])
            if new_hash is not None:
                user.password_hash = new_hash
                await session.execute(
                    update(StaffSession)
                    .where(StaffSession.staff_user_id == user.id, StaffSession.revoked_at.is_(None))
                    .values(revoked_at=self._clock())
                )
            fields = sorted(k for k in changes if changes[k] is not None and k != "password")
            args = {"user_id": str(user.id), "fields": fields, "password_changed": new_hash is not None}
            self._audit(session, principal, "staff_user.update", args)
            return StaffUserOut(
                user.id, user.username, user.display_name, user.role, user.active, user.locked_until
            )

    async def unlock_staff_user(self, principal: StaffPrincipal, user_id: UUID) -> StaffUserOut:
        async with self._session_factory() as session, session.begin():
            user = await session.get(StaffUser, user_id, with_for_update=True)
            if user is None:
                raise OperationRefusedError(ResultCode.NOT_FOUND, "Staff user not found.")
            user.locked_until, user.failed_attempts, user.first_failed_at = None, 0, None
            self._audit(session, principal, "staff_user.unlock", {"user_id": str(user.id)})
            return StaffUserOut(user.id, user.username, user.display_name, user.role, user.active, None)

    @staticmethod
    def _audit(session: AsyncSession, principal: StaffPrincipal, action: str, args: dict[str, Any]) -> None:
        AuditService.record(
            session,
            actor_type="staff",
            actor_id=str(principal.user_id),
            action=action,
            args=args,
            result="OK",
            patient_id=None,
            latency_ms=None,
        )
