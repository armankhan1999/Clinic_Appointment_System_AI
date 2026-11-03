"""Appointment reminders (FR-07, FR-12, E4-S1, E4-S2).

Runs every few minutes in the bot process. Each reminder is claimed with
`INSERT … ON CONFLICT (appointment_id, type) DO NOTHING RETURNING id`, so only the claimer sends it and a
restart can never send it twice (E4-S1-AC3). Delivery is at most once: a crash between claim and send
leaves the row `pending` and the reminder unsent rather than risking a duplicate.

Rules: the 24h reminder is skipped for bookings made less than 24 h ahead (E4-S1-AC2); the 2h reminder
is skipped for bookings made less than 2 h ahead (GAP-19); inside the 2h window only the 2h reminder is
sent and an unsent 24h one is recorded as skipped (GAP-39).
"""

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from clinic.db.models import Appointment, Doctor, Patient, Reminder
from clinic.domain.messages import Button, Reply, callback
from clinic.domain.slots import format_date_long, format_time_12h
from clinic.services.availability import utc_now
from clinic.services.clinic_settings import ClinicSettingsService, ClinicSettingsView

log = structlog.get_logger(__name__)

type ReminderType = Literal["24h", "2h"]

DAY_AHEAD = timedelta(hours=24)
TWO_HOURS = timedelta(hours=2)
DEFAULT_RETRY_DELAYS = (2.0, 4.0, 8.0)  # first attempt plus 3 retries with backoff (E4-S1-AC4)
REMINDER_CONFIRM, REMINDER_RESCHEDULE, REMINDER_CANCEL = "rconf", "rresc", "rcanc"


class DeliveryError(Exception):
    """The message could not be delivered (network, Telegram outage, or the patient blocked the bot)."""


class MessageSender(Protocol):
    async def send(self, chat_id: int, reply: Reply) -> None: ...


@dataclass(frozen=True)
class DueAppointment:
    id: UUID
    reference: str
    start: datetime
    created_at: datetime
    doctor_name: str
    telegram_user_id: int
    existing: frozenset[str]


@dataclass(frozen=True)
class ReminderRunReport:
    sent: int = 0
    skipped: int = 0
    failed: int = 0


def reminder_reply(kind: ReminderType, due: DueAppointment, view: ClinicSettingsView) -> Reply:
    local = due.start.astimezone(view.tz)
    when = f"{format_date_long(local.date())} at {format_time_12h(local)}"
    if kind == "2h":
        return Reply(
            f"Reminder: your appointment with {due.doctor_name} is today at {format_time_12h(local)}.\n"
            f"Address: {view.address}"
        )
    appointment_id = str(due.id)
    return Reply(
        f"Reminder: your appointment {due.reference} with {due.doctor_name} is on {when}.\n"
        f"Address: {view.address}",
        inline_buttons=(
            (
                Button("Confirm", callback(REMINDER_CONFIRM, appointment_id)),
                Button("Reschedule", callback(REMINDER_RESCHEDULE, appointment_id)),
                Button("Cancel", callback(REMINDER_CANCEL, appointment_id)),
            ),
        ),
    )


def decide(due: DueAppointment, now: datetime) -> list[tuple[ReminderType, Literal["pending", "skipped"]]]:
    """Which reminder rows to claim for this appointment now, and whether each is to be sent."""
    lead = due.start - due.created_at
    if due.start - now <= TWO_HOURS:
        plan: list[tuple[ReminderType, Literal["pending", "skipped"]]] = []
        if "24h" not in due.existing:
            plan.append(("24h", "skipped"))  # GAP-39: never two reminders at once
        if "2h" not in due.existing:
            plan.append(("2h", "pending" if lead >= TWO_HOURS else "skipped"))
        return plan
    if "24h" not in due.existing:
        return [("24h", "pending" if lead >= DAY_AHEAD else "skipped")]
    return []


class ReminderService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        settings: ClinicSettingsService,
        sender: MessageSender,
        *,
        clock: Callable[[], datetime] = utc_now,
        retry_delays: Sequence[float] = DEFAULT_RETRY_DELAYS,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._sender = sender
        self._clock = clock
        self._retry_delays = tuple(retry_delays)

    async def run_once(self) -> ReminderRunReport:
        now = self._clock().astimezone(UTC)
        view = await self._settings.get()
        sent = skipped = failed = 0
        for due in await self._due(now):
            for kind, status in decide(due, now):
                if not await self._claim(due.id, kind, status):
                    continue  # another run already handled it
                if status == "skipped":
                    skipped += 1
                elif await self._deliver(due, kind, view, now):
                    sent += 1
                else:
                    failed += 1
        report = ReminderRunReport(sent, skipped, failed)
        log.info("reminder_run", sent=report.sent, skipped=report.skipped, failed=report.failed)
        return report

    async def _due(self, now: datetime) -> list[DueAppointment]:
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(
                        Appointment.id,
                        Appointment.ref,
                        Appointment.start_time,
                        Appointment.created_at,
                        Doctor.name,
                        Patient.telegram_user_id,
                    )
                    .join(Doctor, Doctor.id == Appointment.doctor_id)
                    .join(Patient, Patient.id == Appointment.patient_id)
                    .where(
                        Appointment.status == "booked",
                        Appointment.start_time > now,
                        Appointment.start_time <= now + DAY_AHEAD,
                        Patient.telegram_user_id.is_not(None),
                        Patient.deleted_at.is_(None),
                    )
                )
            ).all()
            if not rows:
                return []
            existing_rows = (
                await session.execute(
                    select(Reminder.appointment_id, Reminder.type).where(
                        Reminder.appointment_id.in_([row[0] for row in rows])
                    )
                )
            ).all()
        existing: dict[UUID, set[str]] = {}
        for appointment_id, kind in existing_rows:
            existing.setdefault(appointment_id, set()).add(kind)
        return [
            DueAppointment(
                row[0], row[1], row[2], row[3], row[4], row[5], frozenset(existing.get(row[0], set()))
            )
            for row in rows
            if row[5] is not None
        ]

    async def _claim(self, appointment_id: UUID, kind: ReminderType, status: str) -> bool:
        async with self._session_factory() as session, session.begin():
            claimed = await session.scalar(
                insert(Reminder)
                .values(appointment_id=appointment_id, type=kind, status=status)
                .on_conflict_do_nothing(index_elements=["appointment_id", "type"])
                .returning(Reminder.id)
            )
        return claimed is not None

    async def _deliver(
        self, due: DueAppointment, kind: ReminderType, view: ClinicSettingsView, now: datetime
    ) -> bool:
        reply = reminder_reply(kind, due, view)
        attempts = 0
        error: str | None = None
        for delay in (0.0, *self._retry_delays):
            if delay:
                await asyncio.sleep(delay)
            attempts += 1
            try:
                await self._sender.send(due.telegram_user_id, reply)
            except DeliveryError as exc:
                error = type(exc).__name__
                log.warning("reminder_delivery_failed", reminder=kind, attempt=attempts)
                continue
            error = None
            break
        async with self._session_factory() as session, session.begin():
            reminder = await session.scalar(
                select(Reminder).where(Reminder.appointment_id == due.id, Reminder.type == kind)
            )
            if reminder is not None:
                reminder.attempts = attempts
                if error is None:
                    reminder.status, reminder.sent_at = "sent", now
                else:
                    reminder.status, reminder.last_error = "failed", error
            if error is not None:
                appointment = await session.get(Appointment, due.id)
                if appointment is not None:
                    appointment.staff_attention_reason = "reminder_failed"
                    appointment.staff_attention_at = now
        if error is not None:
            log.error("reminder_failed", reminder=kind, attempts=attempts)
        return error is None
