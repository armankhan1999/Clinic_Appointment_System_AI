"""Clinic-side change notices from the outbox (FR-13, E4-S4).

The staff API writes `notifications` rows in the same transaction as a cancellation or leave; this drain
(run by the bot, which owns the Telegram token) sends them. Rows are leased with `FOR UPDATE SKIP LOCKED`
and a short `next_attempt_at` push, so no transaction is open during the network call and two drains
never send the same row. Delivery is at least once: a crash after sending but before recording repeats
the notice when the lease ends, which is preferable to a patient missing a cancellation.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from clinic.db.models import Appointment, Doctor, Notification, Patient
from clinic.domain.messages import Button, Reply, callback
from clinic.domain.slots import format_date_long, format_time_12h
from clinic.services.availability import utc_now
from clinic.services.clinic_settings import ClinicSettingsService
from clinic.services.reminders import DeliveryError, MessageSender

log = structlog.get_logger(__name__)

BATCH_SIZE = 20
LEASE = timedelta(minutes=5)
BACKOFF = (timedelta(minutes=1), timedelta(minutes=5))  # waits after the first and second failure
MAX_ATTEMPTS = 3
REBOOK = "rebook"


class NotificationService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        settings: ClinicSettingsService,
        sender: MessageSender,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._sender = sender
        self._clock = clock

    async def drain(self) -> int:
        """Send every due notice once. Returns how many were delivered."""
        now = self._clock().astimezone(UTC)
        delivered = 0
        for notification_id in await self._lease(now):
            if await self._send_one(notification_id, now):
                delivered += 1
        return delivered

    async def _lease(self, now: datetime) -> list[UUID]:
        async with self._session_factory() as session, session.begin():
            rows = (
                await session.scalars(
                    select(Notification)
                    .where(Notification.status == "pending", Notification.next_attempt_at <= now)
                    .order_by(Notification.next_attempt_at)
                    .limit(BATCH_SIZE)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            for row in rows:
                row.next_attempt_at = now + LEASE
            return [row.id for row in rows]

    async def _send_one(self, notification_id: UUID, now: datetime) -> bool:
        view = await self._settings.get()
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(Notification, Appointment, Doctor.name, Patient.telegram_user_id)
                    .join(Appointment, Appointment.id == Notification.appointment_id)
                    .join(Doctor, Doctor.id == Appointment.doctor_id)
                    .join(Patient, Patient.id == Notification.patient_id)
                    .where(Notification.id == notification_id)
                )
            ).first()
        if row is None:
            return False
        notice, appointment, doctor_name, telegram_user_id = row
        if telegram_user_id is None:  # the patient deleted their data meanwhile
            await self._record(notification_id, now, error="unreachable", give_up=True)
            return False
        local = appointment.start_time.astimezone(view.tz)
        reply = Reply(
            f"Sorry, the clinic has cancelled your appointment {appointment.ref} with {doctor_name} on "
            f"{format_date_long(local.date())} at {format_time_12h(local)}.\nReason: {notice.reason}",
            inline_buttons=((Button("Reschedule", callback(REBOOK, str(appointment.id))),),),
        )
        try:
            await self._sender.send(telegram_user_id, reply)
        except DeliveryError as exc:
            await self._record(notification_id, now, error=type(exc).__name__)
            return False
        await self._record(notification_id, now, error=None)
        return True

    async def _record(
        self, notification_id: UUID, now: datetime, *, error: str | None, give_up: bool = False
    ) -> None:
        async with self._session_factory() as session, session.begin():
            notice = await session.get(Notification, notification_id, with_for_update=True)
            if notice is None:
                return
            notice.attempts += 1
            if error is None:
                notice.status, notice.sent_at = "sent", now
                return
            notice.last_error = error
            if give_up or notice.attempts >= MAX_ATTEMPTS:
                notice.status = "failed"
                if not give_up:  # E4-S4-AC2: staff call the patient instead
                    appointment = await session.get(Appointment, notice.appointment_id)
                    if appointment is not None:
                        appointment.staff_attention_reason = "notification_failed"
                        appointment.staff_attention_at = now
                log.error("notification_failed", kind=notice.kind, attempts=notice.attempts)
            else:
                notice.next_attempt_at = now + BACKOFF[min(notice.attempts, len(BACKOFF)) - 1]
                log.warning("notification_retry", kind=notice.kind, attempts=notice.attempts)
