"""Reminders: E4-S1-AC1..AC4, E4-S2-AC1/AC2, GAP-19 (2h only if booked 2h+ ahead), GAP-39 (never both)."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from clinic.db.models import Appointment, Doctor, Reminder
from clinic.domain.messages import Reply
from clinic.services.clinic_settings import ClinicSettingsService
from clinic.services.reminders import DeliveryError, ReminderService

from .factories import make_appointment, make_clinic_settings, make_doctor, make_patient

Factory = async_sessionmaker[AsyncSession]
IST = ZoneInfo("Asia/Kolkata")
START = datetime(2030, 1, 9, 10, 30, tzinfo=IST)


class FakeSender:
    """Stands in for Telegram, the external dependency."""

    def __init__(self, failures: int = 0) -> None:
        self.sent: list[tuple[int, Reply]] = []
        self.calls = 0
        self.failures = failures

    async def send(self, chat_id: int, reply: Reply) -> None:
        self.calls += 1
        if self.calls <= self.failures:
            raise DeliveryError("telegram unavailable")
        self.sent.append((chat_id, reply))


async def _appointment(
    session_factory: Factory,
    *,
    telegram_user_id: int | None = 4242,
    status: str = "booked",
    booked_ahead: timedelta = timedelta(days=3),
) -> tuple[Appointment, Doctor]:
    async with session_factory() as session:
        await make_clinic_settings(session)
        doctor = await make_doctor(session, name="Dr. Meera Iyer")
        patient = await make_patient(session, telegram_user_id=telegram_user_id)
        appointment = await make_appointment(
            session, doctor=doctor, patient=patient, start=START, status=status
        )
        appointment.created_at = START - booked_ahead
        await session.commit()
    return appointment, doctor


def _service(session_factory: Factory, sender: FakeSender, now: datetime) -> ReminderService:
    return ReminderService(
        session_factory,
        ClinicSettingsService(session_factory),
        sender,
        clock=lambda: now,
        retry_delays=(0, 0, 0),
    )


async def _rows(session_factory: Factory) -> dict[str, str]:
    async with session_factory() as session:
        return {r.type: r.status for r in (await session.scalars(select(Reminder))).all()}


async def test_24h_reminder_has_details_address_and_buttons(session_factory: Factory) -> None:
    appointment, _ = await _appointment(session_factory)
    sender = FakeSender()
    await _service(session_factory, sender, START - timedelta(hours=23)).run_once()
    [(chat_id, reply)] = sender.sent
    assert chat_id == 4242
    for part in (
        "Dr. Meera Iyer",
        "Wednesday, 9 January 2030",
        "10:30 AM",
        "12 Example Road",
        appointment.ref,
    ):
        assert part in reply.text
    labels = [b.text for row in reply.inline_buttons for b in row]
    assert labels == ["Confirm", "Reschedule", "Cancel"]
    assert all(str(appointment.id) in (b.callback_data or "") for row in reply.inline_buttons for b in row)
    assert await _rows(session_factory) == {"24h": "sent"}


async def test_nothing_is_sent_more_than_24_hours_ahead(session_factory: Factory) -> None:
    await _appointment(session_factory)
    sender = FakeSender()
    await _service(session_factory, sender, START - timedelta(hours=25)).run_once()
    assert sender.sent == []


async def test_booking_made_less_than_24h_ahead_skips_the_24h_reminder(session_factory: Factory) -> None:
    await _appointment(session_factory, booked_ahead=timedelta(hours=10))
    sender = FakeSender()
    await _service(session_factory, sender, START - timedelta(hours=8)).run_once()
    assert sender.sent == []
    assert await _rows(session_factory) == {"24h": "skipped"}


async def test_reminders_are_never_sent_twice_even_after_a_restart(session_factory: Factory) -> None:
    await _appointment(session_factory)
    sender = FakeSender()
    now = START - timedelta(hours=23)
    await _service(session_factory, sender, now).run_once()
    await _service(session_factory, sender, now + timedelta(minutes=5)).run_once()  # new instance = restart
    assert len(sender.sent) == 1


async def test_two_hour_reminder_is_short_and_replaces_a_missed_24h_one(session_factory: Factory) -> None:
    await _appointment(session_factory)
    sender = FakeSender()
    await _service(session_factory, sender, START - timedelta(minutes=110)).run_once()
    [(_, reply)] = sender.sent
    assert "10:30 AM" in reply.text
    assert "12 Example Road" in reply.text
    assert await _rows(session_factory) == {"24h": "skipped", "2h": "sent"}, "GAP-39: never both at once"


async def test_two_hour_reminder_skipped_for_bookings_made_inside_two_hours(session_factory: Factory) -> None:
    await _appointment(session_factory, booked_ahead=timedelta(minutes=90))
    sender = FakeSender()
    await _service(session_factory, sender, START - timedelta(minutes=60)).run_once()
    assert sender.sent == []
    assert (await _rows(session_factory))["2h"] == "skipped"


async def test_cancelled_and_unreachable_patients_get_nothing(session_factory: Factory) -> None:
    await _appointment(session_factory, status="cancelled")
    sender = FakeSender()
    await _service(session_factory, sender, START - timedelta(minutes=60)).run_once()
    assert sender.sent == []


async def test_walk_in_patient_without_telegram_gets_nothing(session_factory: Factory) -> None:
    await _appointment(session_factory, telegram_user_id=None)
    sender = FakeSender()
    await _service(session_factory, sender, START - timedelta(hours=23)).run_once()
    assert sender.sent == []


async def test_delivery_is_retried_three_times_then_flagged_for_staff(session_factory: Factory) -> None:
    appointment, _ = await _appointment(session_factory)
    sender = FakeSender(failures=10)
    await _service(session_factory, sender, START - timedelta(hours=23)).run_once()
    assert sender.calls == 4, "the first attempt plus 3 retries"
    async with session_factory() as session:
        reminder = await session.scalar(select(Reminder))
        stored = await session.get_one(Appointment, appointment.id)
    assert reminder is not None
    assert (reminder.status, reminder.attempts) == ("failed", 4)
    assert reminder.last_error == "DeliveryError"
    assert stored.staff_attention_reason == "reminder_failed"


async def test_a_retry_that_succeeds_is_recorded_as_sent(session_factory: Factory) -> None:
    await _appointment(session_factory)
    sender = FakeSender(failures=2)
    await _service(session_factory, sender, START - timedelta(hours=23)).run_once()
    assert len(sender.sent) == 1
    assert await _rows(session_factory) == {"24h": "sent"}
