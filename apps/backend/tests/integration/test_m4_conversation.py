"""E4-S3 reminder buttons, E5-S1 FAQ, E5-S4 handoff + GAP-32, E7-S3 limits, E7-S4-AC3 quoted data."""

from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from clinic.agent.llm import ToolResults
from clinic.agent.loop import AgentLoop, AuditEntry
from clinic.agent.memory import ConversationMemory
from clinic.agent.rate_limit import RateLimiter
from clinic.agent.tools import ToolResult, build_registry
from clinic.conversation.service import ConversationService
from clinic.db.models import Appointment, ClinicInfo, Doctor, HandoffTicket, Patient
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


async def _no_audit(entry: AuditEntry) -> None:
    return None


async def _setup(session_factory: Factory) -> tuple[Doctor, Patient]:
    async with session_factory() as session:
        await make_clinic_settings(session)
        doctor = await make_doctor(session, name="Dr. Meera Iyer")
        for weekday in range(5):
            await add_schedule(session, doctor, weekday, time(9), time(11))
        patient = await make_patient(session, telegram_user_id=USER.telegram_user_id, name="Asha Rao")
        session.add(
            ClinicInfo(topic="parking", aliases=["car", "bike"], answer="Free parking in the basement.")
        )
        await session.commit()
    return doctor, patient


def build(session_factory: Factory, llm: Any, limiter: RateLimiter | None = None) -> ConversationService:
    return ConversationService(
        patients=PatientService(session_factory),
        settings=ClinicSettingsService(session_factory),
        agent=AgentLoop(llm, build_registry(), _no_audit, actor_id="test"),
        memory=ConversationMemory(),
        services=agent_services(session_factory, clock=lambda: NOW),
        clock=lambda: NOW,
        rate_limiter=limiter,
    )


def _buttons(replies: list[Reply]) -> dict[str, str]:
    return {b.text: b.callback_data or "" for r in replies for row in r.inline_buttons for b in row}


def _final_results(llm: ScriptedLLM) -> list[ToolResult]:
    return [res for item in llm.transcripts[-1] if isinstance(item, ToolResults) for _, res in item.results]


async def _book(session_factory: Factory, doctor: Doctor, patient: Patient, start: datetime) -> Appointment:
    async with session_factory() as session:
        appointment = await make_appointment(session, doctor=doctor, patient=patient, start=start)
        await session.commit()
        return appointment


# ---- E4-S3 reminder buttons ------------------------------------------------------------------


async def test_reminder_confirm_marks_the_appointment_confirmed(session_factory: Factory) -> None:
    doctor, patient = await _setup(session_factory)
    appointment = await _book(session_factory, doctor, patient, datetime(2030, 1, 8, 9, 0, tzinfo=IST))
    [reply] = await build(session_factory, ScriptedLLM()).handle_callback(USER, f"v1:rconf:{appointment.id}")
    assert "see you" in reply.text.lower()
    async with session_factory() as session:
        assert (await session.get_one(Appointment, appointment.id)).patient_confirmed_at is not None


async def test_reminder_cancel_starts_the_cancel_flow_with_its_confirm_step(session_factory: Factory) -> None:
    doctor, patient = await _setup(session_factory)
    appointment = await _book(session_factory, doctor, patient, datetime(2030, 1, 8, 9, 0, tzinfo=IST))
    service = build(session_factory, ScriptedLLM())
    [summary] = await service.handle_callback(USER, f"v1:rcanc:{appointment.id}")
    assert set(_buttons([summary])) == {"Confirm cancel", "Keep it"}
    [done] = await service.handle_callback(USER, _buttons([summary])["Confirm cancel"])
    assert "Cancelled" in done.text


async def test_reminder_reschedule_hands_over_to_the_agent_with_context(session_factory: Factory) -> None:
    doctor, patient = await _setup(session_factory)
    appointment = await _book(session_factory, doctor, patient, datetime(2030, 1, 8, 9, 0, tzinfo=IST))
    llm = ScriptedLLM(text_turn("Which day would suit you?"))
    service = build(session_factory, llm)
    [reply] = await service.handle_callback(USER, f"v1:rresc:{appointment.id}")
    assert "which day" in reply.text.lower()
    await service.handle_text(USER, "Thursday please")
    assert appointment.ref in repr(llm.transcripts[-1]), "the model knows which appointment to move"


async def test_reminder_buttons_after_the_start_are_refused(session_factory: Factory) -> None:
    doctor, patient = await _setup(session_factory)
    started = await _book(session_factory, doctor, patient, datetime(2030, 1, 7, 7, 30, tzinfo=IST))
    service = build(session_factory, ScriptedLLM())
    for kind in ("rconf", "rresc", "rcanc"):
        [reply] = await service.handle_callback(USER, f"v1:{kind}:{started.id}")
        assert "can no longer be changed" in reply.text


async def test_reminder_change_buttons_inside_the_cut_off_point_to_the_clinic(
    session_factory: Factory,
) -> None:
    """E4-S3-AC2: Reschedule and Cancel keep the E3 cut-off; Confirm attendance still works."""
    doctor, patient = await _setup(session_factory)
    soon = await _book(session_factory, doctor, patient, datetime(2030, 1, 7, 9, 30, tzinfo=IST))
    service = build(session_factory, ScriptedLLM())
    for kind in ("rresc", "rcanc"):
        [reply] = await service.handle_callback(USER, f"v1:{kind}:{soon.id}")
        assert "too close to the appointment" in reply.text
        assert "call the clinic on" in reply.text
        assert not reply.inline_buttons, "no Confirm step is offered"
    [confirmed] = await service.handle_callback(USER, f"v1:rconf:{soon.id}")
    assert "see you" in confirmed.text.lower()
    async with session_factory() as session:
        assert (await session.get_one(Appointment, soon.id)).status == "booked"


async def test_forged_reminder_button_for_someone_elses_appointment_does_nothing(
    session_factory: Factory,
) -> None:
    doctor, _ = await _setup(session_factory)
    async with session_factory() as session:
        other = await make_patient(session)
        theirs = await make_appointment(
            session, doctor=doctor, patient=other, start=datetime(2030, 1, 8, 9, tzinfo=IST)
        )
        await session.commit()
    service = build(session_factory, ScriptedLLM())
    for kind in ("rconf", "rcanc"):
        [reply] = await service.handle_callback(USER, f"v1:{kind}:{theirs.id}")
        assert "expired" in reply.text or "not found" in reply.text.lower()
    async with session_factory() as session:
        stored = await session.get_one(Appointment, theirs.id)
    assert (stored.status, stored.patient_confirmed_at) == ("booked", None)


# ---- E5-S1 FAQ and E7-S4-AC3 ------------------------------------------------------------------


async def test_clinic_info_comes_only_from_the_approved_entry_as_quoted_data(
    session_factory: Factory,
) -> None:
    await _setup(session_factory)
    llm = ScriptedLLM(call_turn(("get_clinic_info", {"topic": "car"})), text_turn("Parking is free."))
    await build(session_factory, llm).handle_text(USER, "where do I park?")
    [result] = _final_results(llm)
    assert result.code == ResultCode.OK
    assert result.data == {"topic": "parking", "approved_answer": "Free parking in the basement."}


async def test_unknown_topic_is_not_found_with_the_known_topics(session_factory: Factory) -> None:
    await _setup(session_factory)
    llm = ScriptedLLM(
        call_turn(("get_clinic_info", {"topic": "wifi password"})), text_turn("I don't know that.")
    )
    await build(session_factory, llm).handle_text(USER, "wifi?")
    [result] = _final_results(llm)
    assert result.code == ResultCode.NOT_FOUND
    assert result.data["known_topics"] == ["parking"]


async def test_an_updated_answer_is_used_on_the_next_question(session_factory: Factory) -> None:
    await _setup(session_factory)
    llm = ScriptedLLM(
        call_turn(("get_clinic_info", {"topic": "parking"})),
        text_turn("ok"),
        call_turn(("get_clinic_info", {"topic": "parking"})),
        text_turn("ok"),
    )
    service = build(session_factory, llm)
    await service.handle_text(USER, "parking?")
    async with session_factory() as session:
        entry = await session.scalar(select(ClinicInfo).where(ClinicInfo.topic == "parking"))
        assert entry is not None
        entry.answer = "Parking is now on level 2."
        await session.commit()
    await service.handle_text(USER, "parking again?")
    assert _final_results(llm)[-1].data["approved_answer"] == "Parking is now on level 2."


# ---- E5-S4 handoff and GAP-32 -------------------------------------------------------------------


async def test_handoff_opens_one_ticket_and_shares_phone_and_hours(session_factory: Factory) -> None:
    await _setup(session_factory)
    llm = ScriptedLLM(
        call_turn(("handoff_to_staff", {"reason": "patient_requested"})),
        text_turn("Staff will call you."),
        call_turn(("handoff_to_staff", {"reason": "patient_requested"})),
        text_turn("Staff will call you."),
    )
    service = build(session_factory, llm)
    await service.handle_text(USER, "I want a human")
    first = _final_results(llm)[0]
    await service.handle_text(USER, "please, a human")
    second = _final_results(llm)[-1]
    assert (first.code, second.code) == (ResultCode.CREATED, ResultCode.ALREADY_OPEN)
    assert first.data["clinic_phone"] == "+12025550100"
    assert "Monday to Saturday" in first.data["staff_hours"]
    async with session_factory() as session:
        assert len((await session.scalars(select(HandoffTicket))).all()) == 1


async def test_three_failures_of_one_tool_offer_a_talk_to_staff_button(session_factory: Factory) -> None:
    await _setup(session_factory)
    bad = {"doctor_id": "00000000-0000-0000-0000-000000000000", "date": "tomorrow"}
    turns = []
    for _ in range(3):
        turns += [call_turn(("check_availability", bad)), text_turn("Sorry, try again.")]
    service = build(session_factory, ScriptedLLM(*turns))
    replies: list[Reply] = []
    for _ in range(3):
        replies = await service.handle_text(USER, "is the doctor free?")
    talk = _buttons(replies)["Talk to staff"]
    [handed] = await service.handle_callback(USER, talk)
    assert "+12025550100" in handed.text
    async with session_factory() as session:
        ticket = await session.scalar(select(HandoffTicket))
    assert ticket is not None
    assert ticket.reason == "agent_failed"


# ---- E7-S3 limits -------------------------------------------------------------------------------


async def test_too_many_messages_get_one_notice_then_silence(session_factory: Factory) -> None:
    await _setup(session_factory)
    limiter = RateLimiter(max_messages=2, clock=lambda: 0.0)
    llm = ScriptedLLM(text_turn("one"), text_turn("two"))
    service = build(session_factory, llm, limiter)
    await service.handle_text(USER, "a")
    await service.handle_text(USER, "b")
    [notice] = await service.handle_text(USER, "c")
    assert "slow down" in notice.text.lower()
    assert await service.handle_text(USER, "d") == []
    assert len(llm.transcripts) == 2, "dropped messages never reach the LLM"


async def test_messages_over_1000_characters_are_rejected_without_the_llm(session_factory: Factory) -> None:
    await _setup(session_factory)
    llm = ScriptedLLM()
    replies = await build(session_factory, llm).handle_text(USER, "x" * 1001)
    assert "too long" in replies[-1].text
    assert llm.transcripts == []
