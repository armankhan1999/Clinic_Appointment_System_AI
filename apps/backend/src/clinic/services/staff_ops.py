"""Receptionist operations behind the staff API (E6-S2, E6-S4, E6-S5, E5-S3-AC3, E5-S4-AC2, E4-S4).

All appointment rows for a screen are loaded with a fixed number of queries (no N+1). Every write is
audited with actor_type "staff" and the staff user id (GAP-18).
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from clinic.db.models import (
    Appointment,
    Doctor,
    EmergencyAlert,
    HandoffTicket,
    Notification,
    Patient,
    Reminder,
)
from clinic.domain.appointments import AppointmentStatus, can_transition
from clinic.domain.patients import InvalidNameError, InvalidPhoneError, normalise_name, normalise_phone
from clinic.domain.results import ResultCode
from clinic.domain.slots import format_time_12h
from clinic.services.audit import AuditService
from clinic.services.availability import AvailabilityService, utc_now
from clinic.services.booking import BookingService
from clinic.services.clinic_settings import ClinicSettingsService, ClinicSettingsView
from clinic.services.staff_auth import StaffPrincipal

DEFAULT_PHONE_REGION = "IN"


class OperationRefusedError(Exception):
    """A staff operation was refused; the API maps `code` to an HTTP status and the error envelope."""

    def __init__(self, code: ResultCode | str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = str(code)
        self.message = message
        self.details = details or {}


@dataclass(frozen=True)
class PatientRefOut:
    id: UUID
    full_name: str
    phone: str | None


@dataclass(frozen=True)
class AttentionOut:
    reason: str
    at: datetime


@dataclass(frozen=True)
class AppointmentOut:
    id: UUID
    reference: str
    doctor_id: UUID
    doctor_name: str
    start: datetime
    end: datetime
    date: str
    time_label: str
    status: str
    source: str
    patient: PatientRefOut
    reminders: dict[str, str | None]
    patient_confirmed: bool
    staff_attention: AttentionOut | None
    can_mark_attendance: bool


@dataclass(frozen=True)
class DoctorDayOut:
    doctor_id: UUID
    name: str
    specialty: str
    appointments: list[AppointmentOut] = field(default_factory=list)


@dataclass(frozen=True)
class TicketOut:
    id: UUID
    reason: str
    created_at: datetime
    patient: PatientRefOut


@dataclass(frozen=True)
class AlertOut:
    id: UUID
    created_at: datetime
    patient: PatientRefOut | None
    telegram_user_id: int | None


@dataclass(frozen=True)
class AttentionPanelOut:
    tickets: list[TicketOut]
    alerts: list[AlertOut]
    flagged: list[AppointmentOut]


@dataclass(frozen=True)
class NewPatient:
    full_name: str
    phone: str
    verbal_consent: bool


def _patient_ref(patient: Patient) -> PatientRefOut:
    return PatientRefOut(patient.id, patient.full_name or "Deleted patient", patient.phone)


async def appointment_rows(
    session: AsyncSession, appointments: Sequence[Appointment], view: ClinicSettingsView, now: datetime
) -> list[AppointmentOut]:
    """Three queries for any number of appointments: patients, doctors and reminders."""
    if not appointments:
        return []
    ids = [a.id for a in appointments]
    patients = {
        p.id: p
        for p in (
            await session.scalars(select(Patient).where(Patient.id.in_({a.patient_id for a in appointments})))
        ).all()
    }
    doctors = {
        d.id: d
        for d in (
            await session.scalars(select(Doctor).where(Doctor.id.in_({a.doctor_id for a in appointments})))
        ).all()
    }
    reminders: dict[UUID, dict[str, str | None]] = {i: {"24h": None, "2h": None} for i in ids}
    for reminder in (await session.scalars(select(Reminder).where(Reminder.appointment_id.in_(ids)))).all():
        reminders[reminder.appointment_id][reminder.type] = reminder.status
    rows = []
    for a in appointments:
        local = a.start_time.astimezone(view.tz)
        attention = (
            AttentionOut(a.staff_attention_reason, a.staff_attention_at)
            if a.staff_attention_reason and a.staff_attention_at
            else None
        )
        rows.append(
            AppointmentOut(
                id=a.id,
                reference=a.ref,
                doctor_id=a.doctor_id,
                doctor_name=doctors[a.doctor_id].name,
                start=a.start_time,
                end=a.end_time,
                date=local.date().isoformat(),
                time_label=format_time_12h(local),
                status=a.status,
                source=a.source,
                patient=_patient_ref(patients[a.patient_id]),
                reminders=reminders[a.id],
                patient_confirmed=a.patient_confirmed_at is not None,
                staff_attention=attention,
                can_mark_attendance=a.start_time <= now and a.status in {"booked", "completed", "no_show"},
            )
        )
    return rows


class StaffOpsService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        settings: ClinicSettingsService,
        booking: BookingService,
        availability: AvailabilityService,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._booking = booking
        self._availability = availability
        self._clock = clock

    # ---- reads -----------------------------------------------------------------------------------

    async def schedule(self, day: date) -> list[DoctorDayOut]:
        """E6-S2-AC1: every active doctor's appointments for one clinic day, all statuses, by start time."""
        view = await self._settings.get()
        start = datetime.combine(day, time.min, tzinfo=view.tz)
        async with self._session_factory() as session:
            doctors = (
                await session.scalars(select(Doctor).where(Doctor.active.is_(True)).order_by(Doctor.name))
            ).all()
            appointments = (
                await session.scalars(
                    select(Appointment)
                    .where(
                        Appointment.start_time >= start, Appointment.start_time < start + timedelta(days=1)
                    )
                    .order_by(Appointment.start_time)
                )
            ).all()
            rows = await appointment_rows(session, appointments, view, self._clock())
        return [
            DoctorDayOut(d.id, d.name, d.specialty, [r for r in rows if r.doctor_id == d.id]) for d in doctors
        ]

    async def clinic_today(self) -> tuple[date, str]:
        """Today in the clinic's time zone, so the dashboard never relies on the PC's clock or zone."""
        view = await self._settings.get()
        return self._clock().astimezone(view.tz).date(), view.tz.key

    async def attention(self) -> AttentionPanelOut:
        """E6-S2-AC3: open tickets, unacknowledged emergency alerts and flagged booked appointments."""
        view = await self._settings.get()
        async with self._session_factory() as session:
            tickets = (
                await session.execute(
                    select(HandoffTicket, Patient)
                    .join(Patient, Patient.id == HandoffTicket.patient_id)
                    .where(HandoffTicket.status == "open")
                    .order_by(HandoffTicket.created_at)
                )
            ).all()
            alerts = (
                await session.execute(
                    select(EmergencyAlert, Patient)
                    .outerjoin(Patient, Patient.id == EmergencyAlert.patient_id)
                    .where(EmergencyAlert.acknowledged_at.is_(None))
                    .order_by(EmergencyAlert.created_at)
                )
            ).all()
            flagged = (
                await session.scalars(
                    select(Appointment)
                    .where(Appointment.staff_attention_reason.is_not(None))
                    .order_by(Appointment.start_time)
                )
            ).all()
            flagged_rows = await appointment_rows(session, flagged, view, self._clock())
        return AttentionPanelOut(
            tickets=[TicketOut(t.id, t.reason, t.created_at, _patient_ref(p)) for t, p in tickets],
            alerts=[
                AlertOut(
                    a.id, a.created_at, _patient_ref(p) if p else None, None if p else a.telegram_user_id
                )
                for a, p in alerts
            ],
            flagged=flagged_rows,
        )

    async def find_patients(self, phone: str) -> list[PatientRefOut]:
        """E6-S4-AC1: exact lookup on the normalised phone only, never a listing."""
        try:
            normalised = normalise_phone(phone, DEFAULT_PHONE_REGION)
        except InvalidPhoneError as exc:
            raise OperationRefusedError(
                ResultCode.VALIDATION_ERROR, "That is not a valid phone number."
            ) from exc
        async with self._session_factory() as session:
            patients = (
                await session.scalars(
                    select(Patient).where(Patient.phone == normalised, Patient.deleted_at.is_(None))
                )
            ).all()
        return [_patient_ref(p) for p in patients]

    async def appointment(self, appointment_id: UUID) -> AppointmentOut:
        view = await self._settings.get()
        async with self._session_factory() as session:
            row = await session.get(Appointment, appointment_id)
            if row is None:
                raise OperationRefusedError(ResultCode.NOT_FOUND, "Appointment not found.")
            [out] = await appointment_rows(session, [row], view, self._clock())
        return out

    # ---- writes -----------------------------------------------------------------------------------

    async def book(
        self,
        principal: StaffPrincipal,
        *,
        doctor_id: UUID,
        start: datetime,
        patient_id: UUID | None,
        new_patient: NewPatient | None,
    ) -> AppointmentOut:
        """E6-S4-AC1/AC2: walk-in or phone booking through the same booking rules as the bot."""
        if new_patient is not None:
            patient_id = await self._create_walk_in(principal, new_patient)
        if patient_id is None:
            raise OperationRefusedError(ResultCode.VALIDATION_ERROR, "Choose a patient or enter a new one.")
        outcome = await self._booking.book(
            patient_id=patient_id,
            doctor_id=doctor_id,
            slot_start=start,
            source="staff",
            actor_type="staff",
            staff_user_id=principal.user_id,
        )
        if outcome.code is not ResultCode.OK or outcome.appointment_id is None:
            messages = {
                ResultCode.SLOT_TAKEN: "That slot was just taken. Please pick another time.",
                ResultCode.SLOT_UNAVAILABLE: "That time is not a free slot for this doctor.",
                ResultCode.LIMIT_REACHED: "The patient has reached the booking limit.",
                ResultCode.NOT_FOUND: "Doctor or patient not found.",
            }
            details = (
                {"alternatives": [s.start.isoformat() for s in outcome.alternatives]}
                if outcome.alternatives
                else {}
            )
            raise OperationRefusedError(
                outcome.code, messages.get(outcome.code, "The booking was refused."), details
            )
        return await self.appointment(outcome.appointment_id)

    async def _create_walk_in(self, principal: StaffPrincipal, new: NewPatient) -> UUID:
        if not new.verbal_consent:
            raise OperationRefusedError(
                ResultCode.VALIDATION_ERROR, "Record the patient's verbal consent first."
            )
        try:
            full_name = normalise_name(new.full_name)
            phone = normalise_phone(new.phone, DEFAULT_PHONE_REGION)
        except (InvalidNameError, InvalidPhoneError) as exc:
            raise OperationRefusedError(ResultCode.VALIDATION_ERROR, str(exc)) from exc
        async with self._session_factory() as session, session.begin():
            if await session.scalar(select(Patient.id).where(Patient.phone == phone)) is not None:
                raise OperationRefusedError(
                    "CONFLICT", "A patient with this phone already exists. Look them up by phone instead."
                )
            patient = Patient(
                phone=phone,
                full_name=full_name,
                consent_at=self._clock(),
                consent_source="staff_verbal",
                registered_via="staff",
            )
            session.add(patient)
            await session.flush()
            self._audit(session, principal, "patient.create", {"source": "walk_in"}, "OK", patient.id)
            return patient.id

    async def cancel(self, principal: StaffPrincipal, appointment_id: UUID, reason: str) -> AppointmentOut:
        """E6-S4-AC3: staff are not bound by the bot cut-off (GAP-21); linked patients get notices."""
        now = self._clock()
        async with self._session_factory() as session, session.begin():
            appointment = await session.get(Appointment, appointment_id, with_for_update=True)
            if appointment is None:
                raise OperationRefusedError(ResultCode.NOT_FOUND, "Appointment not found.")
            if appointment.status == "cancelled":
                raise OperationRefusedError(
                    ResultCode.ALREADY_CANCELLED, "This appointment is already cancelled."
                )
            if not can_transition(
                AppointmentStatus(appointment.status), AppointmentStatus.CANCELLED, actor="staff"
            ):
                raise OperationRefusedError("CONFLICT", "Only booked appointments can be cancelled.")
            appointment.status = "cancelled"
            appointment.cancelled_at = now
            appointment.cancelled_by_kind = "staff"
            appointment.cancel_reason = reason
            patient = await session.get_one(Patient, appointment.patient_id)
            if patient.telegram_user_id is not None and patient.deleted_at is None:
                session.add(
                    Notification(
                        appointment_id=appointment.id,
                        patient_id=patient.id,
                        kind="clinic_cancelled",
                        reason=reason,
                        next_attempt_at=now,
                    )
                )
            self._audit(
                session,
                principal,
                "appointment.staff_cancel",
                {"appointment_id": str(appointment.id)},
                "OK",
                patient.id,
            )
        return await self.appointment(appointment_id)

    async def mark_attendance(
        self, principal: StaffPrincipal, appointment_id: UUID, status: Literal["completed", "no_show"]
    ) -> AppointmentOut:
        """E6-S5: only after the start; switching completed and no_show is admin-only (GAP-22)."""
        now = self._clock()
        async with self._session_factory() as session, session.begin():
            appointment = await session.get(Appointment, appointment_id, with_for_update=True)
            if appointment is None:
                raise OperationRefusedError(ResultCode.NOT_FOUND, "Appointment not found.")
            if appointment.start_time > now:
                raise OperationRefusedError("CONFLICT", "Attendance can be marked only after the start time.")
            actor: Literal["staff", "admin"] = "admin" if principal.role == "admin" else "staff"
            if not can_transition(
                AppointmentStatus(appointment.status), AppointmentStatus(status), actor=actor
            ):
                if appointment.status in {"completed", "no_show"}:
                    raise OperationRefusedError(
                        ResultCode.FORBIDDEN, "Only an admin can change an attendance mark."
                    )
                raise OperationRefusedError("CONFLICT", "This appointment cannot be marked.")
            appointment.status = status
            appointment.attendance_marked_by = principal.user_id
            appointment.attendance_marked_at = now
            args = {"appointment_id": str(appointment.id), "status": status}
            self._audit(session, principal, "appointment.attendance", args, "OK", appointment.patient_id)
        return await self.appointment(appointment_id)

    async def clear_attention(self, principal: StaffPrincipal, appointment_id: UUID) -> AppointmentOut:
        async with self._session_factory() as session, session.begin():
            appointment = await session.get(Appointment, appointment_id, with_for_update=True)
            if appointment is None:
                raise OperationRefusedError(ResultCode.NOT_FOUND, "Appointment not found.")
            appointment.staff_attention_reason = None
            appointment.staff_attention_at = None
            self._audit(
                session,
                principal,
                "appointment.clear_attention",
                {"appointment_id": str(appointment.id)},
                "OK",
                appointment.patient_id,
            )
        return await self.appointment(appointment_id)

    async def resolve_ticket(self, principal: StaffPrincipal, ticket_id: UUID) -> dict[str, Any]:
        """E5-S4-AC2: status, resolver and time are saved."""
        now = self._clock()
        async with self._session_factory() as session, session.begin():
            ticket = await session.get(HandoffTicket, ticket_id, with_for_update=True)
            if ticket is None:
                raise OperationRefusedError(ResultCode.NOT_FOUND, "Ticket not found.")
            if ticket.status == "open":
                ticket.status, ticket.resolved_by, ticket.resolved_at = "resolved", principal.user_id, now
                self._audit(
                    session,
                    principal,
                    "ticket.resolve",
                    {"ticket_id": str(ticket.id)},
                    "OK",
                    ticket.patient_id,
                )
            return {
                "id": ticket.id,
                "status": ticket.status,
                "resolved_by": ticket.resolved_by,
                "resolved_at": ticket.resolved_at,
            }

    async def acknowledge_alert(self, principal: StaffPrincipal, alert_id: UUID) -> dict[str, Any]:
        now = self._clock()
        async with self._session_factory() as session, session.begin():
            alert = await session.get(EmergencyAlert, alert_id, with_for_update=True)
            if alert is None:
                raise OperationRefusedError(ResultCode.NOT_FOUND, "Alert not found.")
            if alert.acknowledged_at is None:
                alert.acknowledged_by, alert.acknowledged_at = principal.user_id, now
                self._audit(
                    session,
                    principal,
                    "alert.acknowledge",
                    {"alert_id": str(alert.id)},
                    "OK",
                    alert.patient_id,
                )
            return {
                "id": alert.id,
                "acknowledged_by": alert.acknowledged_by,
                "acknowledged_at": alert.acknowledged_at,
            }

    async def free_slots(self, doctor_id: UUID, day: date) -> list[dict[str, str]]:
        view = await self._settings.get()
        result = await self._availability.day(doctor_id, day)
        if result.code is ResultCode.NOT_FOUND:
            raise OperationRefusedError(ResultCode.NOT_FOUND, "Doctor not found.")
        return [
            {"start": slot.start.isoformat(), "time_label": format_time_12h(slot.start.astimezone(view.tz))}
            for slot in result.slots
        ]

    @staticmethod
    def _audit(
        session: AsyncSession,
        principal: StaffPrincipal,
        action: str,
        args: dict[str, str],
        result: str,
        patient_id: UUID | None,
    ) -> None:
        AuditService.record(
            session,
            actor_type="staff",
            actor_id=str(principal.user_id),
            action=action,
            args=args,
            result=result,
            patient_id=patient_id,
            latency_ms=None,
        )
