"""Book with explicit confirmation: E2-S3-AC1..AC5, GAP-17 (stale buttons), D-16 (name rendered by code)."""

from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from clinic.agent.llm import ToolResults
from clinic.agent.loop import AgentLoop, AuditEntry
from clinic.agent.memory import ConversationMemory
from clinic.agent.tools import build_registry
from clinic.conversation.service import ConversationService
from clinic.db.models import Appointment, Doctor, Patient
from clinic.domain.messages import IncomingUser, Reply
from clinic.domain.results import ResultCode
from clinic.services.clinic_settings import ClinicSettingsService
from clinic.services.patients import PatientService

from ..unit.agent_doubles import ScriptedLLM, call_turn, text_turn
from .factories import (
    add_schedule,
    agent_services,
    make_appointment,
    make_clinic_settings,
    make_doctor,
    make_patient,
)

Factory = async_sessionmaker[AsyncSession]
IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2030, 1, 7, 8, 0, tzinfo=IST)  # Monday 08:00
USER = IncomingUser(telegram_user_id=4242)
SLOT = "2030-01-09T09:30:00+05:30"


async def _no_audit(entry: AuditEntry) -> None:
    return None


async def _setup(session_factory: Factory) -> tuple[Doctor, Patient]:
    async with session_factory() as session:
        await make_clinic_settings(session)
        doctor = await make_doctor(session, name="Dr. Meera Iyer")
        await add_schedule(session, doctor, 2, time(9), time(10))  # Wednesday 9-10
        patient = await make_patient(session, telegram_user_id=USER.telegram_user_id, name="Asha Rao")
        await session.commit()
    return doctor, patient


def build(session_factory: Factory, llm: Any) -> ConversationService:
    settings = ClinicSettingsService(session_factory)
    services = agent_services(session_factory, clock=lambda: NOW)
    return ConversationService(
        patients=PatientService(session_factory),
        settings=settings,
        agent=AgentLoop(llm, build_registry(), _no_audit, actor_id="test"),
        memory=ConversationMemory(),
        services=services,
        clock=lambda: NOW,
    )


def _buttons(replies: list[Reply]) -> dict[str, str]:
    return {b.text: b.callback_data or "" for r in replies for row in r.inline_buttons for b in row}


def _booking_turns(doctor: Doctor, slot: str = SLOT) -> list[Any]:
    return [
        call_turn(("book_appointment", {"doctor_id": str(doctor.id), "slot_start": slot})),
        text_turn("Please check the summary and tap Confirm."),
    ]


async def _appointments(session_factory: Factory) -> list[Appointment]:
    async with session_factory() as session:
        return list((await session.scalars(select(Appointment).order_by(Appointment.start_time))).all())


async def test_booking_request_shows_a_summary_and_writes_nothing(session_factory: Factory) -> None:
    doctor, _ = await _setup(session_factory)
    llm = ScriptedLLM(*_booking_turns(doctor))
    replies = await build(session_factory, llm).handle_text(USER, "book Wednesday 9:30")
    summary = next(r for r in replies if r.inline_buttons)
    for part in ("Dr. Meera Iyer", "Wednesday, 9 January 2030", "9:30 AM", "Asha Rao"):
        assert part in summary.text
    assert set(_buttons(replies)) == {"Confirm", "Change"}
    assert await _appointments(session_factory) == []
    tool_results = [item for t in llm.transcripts for item in t if isinstance(item, ToolResults)]
    assert tool_results[0].results[0][1].code == ResultCode.PENDING_CONFIRMATION
    assert "Asha" not in repr(llm.transcripts), "the patient name is rendered by code, not sent to the LLM"


async def test_confirm_books_for_the_session_patient_and_shows_the_reference(
    session_factory: Factory,
) -> None:
    doctor, patient = await _setup(session_factory)
    service = build(session_factory, ScriptedLLM(*_booking_turns(doctor)))
    replies = await service.handle_text(USER, "book Wednesday 9:30")
    [done] = await service.handle_callback(USER, _buttons(replies)["Confirm"])
    assert "APT-000001" in done.text
    [appointment] = await _appointments(session_factory)
    assert (appointment.patient_id, appointment.status, appointment.source) == (patient.id, "booked", "bot")
    assert appointment.start_time == datetime.fromisoformat(SLOT)


async def test_double_tap_on_confirm_books_once(session_factory: Factory) -> None:
    doctor, _ = await _setup(session_factory)
    service = build(session_factory, ScriptedLLM(*_booking_turns(doctor)))
    confirm = _buttons(await service.handle_text(USER, "book"))["Confirm"]
    await service.handle_callback(USER, confirm)
    [again] = await service.handle_callback(USER, confirm)
    assert "expired" in again.text
    assert len(await _appointments(session_factory)) == 1


async def test_slot_taken_before_confirm_offers_nearest_slots_that_can_be_booked(
    session_factory: Factory,
) -> None:
    doctor, _ = await _setup(session_factory)
    service = build(session_factory, ScriptedLLM(*_booking_turns(doctor)))
    confirm = _buttons(await service.handle_text(USER, "book"))["Confirm"]
    async with session_factory() as session:
        other = await make_patient(session)
        await make_appointment(session, doctor=doctor, patient=other, start=datetime.fromisoformat(SLOT))
        await session.commit()
    [taken] = await service.handle_callback(USER, confirm)
    assert "taken" in taken.text
    options = _buttons([taken])
    assert list(options) == ["9:00 AM", "9:15 AM", "9:45 AM"]  # nearest three, in time order (GAP-34)
    [summary] = await service.handle_callback(USER, options["9:45 AM"])
    assert "9:45 AM" in summary.text
    [done] = await service.handle_callback(USER, _buttons([summary])["Confirm"])
    assert "APT-" in done.text
    assert [a.start_time.astimezone(IST).strftime("%H:%M") for a in await _appointments(session_factory)] == [
        "09:30",
        "09:45",
    ]


async def test_limit_is_refused_with_the_reason_and_no_summary(session_factory: Factory) -> None:
    doctor, patient = await _setup(session_factory)
    async with session_factory() as session:
        await make_appointment(
            session, doctor=doctor, patient=patient, start=datetime(2030, 1, 9, 9, 0, tzinfo=IST)
        )
        await session.commit()
    llm = ScriptedLLM(*_booking_turns(doctor))
    replies = await build(session_factory, llm).handle_text(USER, "book another one")
    assert _buttons(replies) == {}
    tool_results = [item for t in llm.transcripts for item in t if isinstance(item, ToolResults)]
    result = tool_results[0].results[0][1]
    assert result.code == ResultCode.LIMIT_REACHED
    assert "same day" in result.data["reason"]


async def test_change_writes_nothing_and_asks_again(session_factory: Factory) -> None:
    doctor, _ = await _setup(session_factory)
    service = build(session_factory, ScriptedLLM(*_booking_turns(doctor)))
    change = _buttons(await service.handle_text(USER, "book"))["Change"]
    [reply] = await service.handle_callback(USER, change)
    assert "prefer" in reply.text
    assert await _appointments(session_factory) == []


async def test_confirm_after_a_restart_is_refused_safely(session_factory: Factory) -> None:
    doctor, _ = await _setup(session_factory)
    confirm = _buttons(
        await build(session_factory, ScriptedLLM(*_booking_turns(doctor))).handle_text(USER, "b")
    )["Confirm"]
    restarted = build(session_factory, ScriptedLLM())
    [reply] = await restarted.handle_callback(USER, confirm)
    assert "expired" in reply.text
    assert await _appointments(session_factory) == []
