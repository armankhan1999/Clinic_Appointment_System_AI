"""Clinic-side change notices from the outbox (E4-S4-AC1/AC2, D-outbox)."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from clinic.db.models import Appointment, Notification
from clinic.services.clinic_settings import ClinicSettingsService
from clinic.services.notifications import NotificationService

from .factories import make_appointment, make_clinic_settings, make_doctor, make_patient
from .test_reminders import FakeSender

Factory = async_sessionmaker[AsyncSession]
IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2030, 1, 7, 8, 0, tzinfo=IST)


async def _queued(session_factory: Factory) -> tuple[Appointment, Notification]:
    async with session_factory() as session:
        await make_clinic_settings(session)
        doctor = await make_doctor(session, name="Dr. Meera Iyer")
        patient = await make_patient(session, telegram_user_id=4242)
        appointment = await make_appointment(
            session,
            doctor=doctor,
            patient=patient,
            start=datetime(2030, 1, 9, 10, 30, tzinfo=IST),
            status="cancelled",
        )
        notice = Notification(
            appointment_id=appointment.id,
            patient_id=patient.id,
            kind="doctor_leave",
            reason="The doctor is on leave that day.",
            next_attempt_at=NOW - timedelta(minutes=1),
        )
        session.add(notice)
        await session.commit()
    return appointment, notice


def _service(session_factory: Factory, sender: FakeSender, now: datetime) -> NotificationService:
    return NotificationService(
        session_factory, ClinicSettingsService(session_factory), sender, clock=lambda: now
    )


async def _notice(session_factory: Factory, notice: Notification) -> Notification:
    async with session_factory() as session:
        return await session.get_one(Notification, notice.id)


async def test_notice_has_reason_details_and_a_reschedule_button(session_factory: Factory) -> None:
    appointment, notice = await _queued(session_factory)
    sender = FakeSender()
    await _service(session_factory, sender, NOW).drain()
    [(chat_id, reply)] = sender.sent
    assert chat_id == 4242
    for part in ("The doctor is on leave that day.", appointment.ref, "Dr. Meera Iyer", "10:30 AM"):
        assert part in reply.text
    [[button]] = reply.inline_buttons
    assert button.text == "Reschedule"
    assert str(appointment.id) in (button.callback_data or "")
    stored = await _notice(session_factory, notice)
    assert (stored.status, stored.attempts) == ("sent", 1)
    assert stored.sent_at is not None


async def test_a_sent_notice_is_not_sent_again(session_factory: Factory) -> None:
    await _queued(session_factory)
    sender = FakeSender()
    await _service(session_factory, sender, NOW).drain()
    await _service(session_factory, sender, NOW + timedelta(minutes=1)).drain()
    assert len(sender.sent) == 1


async def test_failures_back_off_then_flag_the_appointment_for_staff(session_factory: Factory) -> None:
    appointment, notice = await _queued(session_factory)
    sender = FakeSender(failures=10)
    now = NOW
    for _ in range(3):
        await _service(session_factory, sender, now).drain()
        stored = await _notice(session_factory, notice)
        now = stored.next_attempt_at + timedelta(seconds=1)
    assert sender.calls == 3
    stored = await _notice(session_factory, notice)
    assert (stored.status, stored.attempts, stored.last_error) == ("failed", 3, "DeliveryError")
    async with session_factory() as session:
        flagged = await session.get_one(Appointment, appointment.id)
    assert flagged.staff_attention_reason == "notification_failed"
    await _service(session_factory, sender, now + timedelta(hours=1)).drain()
    assert sender.calls == 3, "a failed notice is not retried forever"


async def test_notices_wait_for_their_next_attempt_time(session_factory: Factory) -> None:
    _, notice = await _queued(session_factory)
    sender = FakeSender(failures=1)
    await _service(session_factory, sender, NOW).drain()
    retry_at = (await _notice(session_factory, notice)).next_attempt_at
    assert retry_at > NOW
    await _service(session_factory, sender, retry_at - timedelta(seconds=1)).drain()
    assert sender.calls == 1
    await _service(session_factory, sender, retry_at + timedelta(seconds=1)).drain()
    assert len(sender.sent) == 1
