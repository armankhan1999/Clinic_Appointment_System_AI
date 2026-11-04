"""Manage appointments through the conversation: E3-S1-AC1/AC3, E3-S2-AC1..AC4, E3-S3-AC1..AC4."""

from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from clinic.agent.llm import ToolResults
from clinic.agent.loop import AgentLoop, AuditEntry
from clinic.agent.memory import ConversationMemory
from clinic.agent.tools import ToolResult, build_registry
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


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2030, 1, day, hour, minute, tzinfo=IST)


async def _no_audit(entry: AuditEntry) -> None:
    return None


async def _setup(session_factory: Factory) -> tuple[Doctor, Patient, Patient]:
    async with session_factory() as session:
        await make_clinic_settings(session)
        doctor = await make_doctor(session, name="Dr. Meera Iyer")
        for weekday in range(5):
            await add_schedule(session, doctor, weekday, time(9), time(11))
        me = await make_patient(session, telegram_user_id=USER.telegram_user_id, name="Asha Rao")
        other = await make_patient(session, name="Ravi Kumar")
        await session.commit()
    return doctor, me, other


async def _book(session_factory: Factory, doctor: Doctor, patient: Patient, start: datetime) -> Appointment:
    async with session_factory() as session:
        appointment = await make_appointment(session, doctor=doctor, patient=patient, start=start)
        await session.commit()
        return appointment


def build(session_factory: Factory, llm: Any) -> ConversationService:
    return ConversationService(
        patients=PatientService(session_factory),
        settings=ClinicSettingsService(session_factory),
        agent=AgentLoop(llm, build_registry(), _no_audit, actor_id="test"),
        memory=ConversationMemory(),
        services=agent_services(session_factory, clock=lambda: NOW),
        clock=lambda: NOW,
    )


def _buttons(replies: list[Reply]) -> dict[str, str]:
    return {b.text: b.callback_data or "" for r in replies for row in r.inline_buttons for b in row}


def _tool_results(llm: ScriptedLLM) -> list[ToolResult]:
    """Results in the final transcript (each transcript repeats the earlier ones)."""
    final = llm.transcripts[-1]
    return [result for item in final if isinstance(item, ToolResults) for _, result in item.results]


async def _status(session_factory: Factory, appointment: Appointment) -> str:
    async with session_factory() as session:
        return (await session.get_one(Appointment, appointment.id)).status


async def test_list_shows_only_my_upcoming_appointments(session_factory: Factory) -> None:
    doctor, me, other = await _setup(session_factory)
    mine = await _book(session_factory, doctor, me, at(8, 9))
    await _book(session_factory, doctor, other, at(8, 10))
    llm = ScriptedLLM(call_turn(("list_my_appointments", {})), text_turn("You have one appointment."))
    await build(session_factory, llm).handle_text(USER, "my appointments?")
    [result] = _tool_results(llm)
    assert result.code == ResultCode.OK
    assert [a["reference"] for a in result.data["appointments"]] == [mine.ref]
    assert result.data["appointments"][0]["time"] == "9:00 AM"


async def test_no_appointments_returns_none(session_factory: Factory) -> None:
    await _setup(session_factory)
    llm = ScriptedLLM(call_turn(("list_my_appointments", {})), text_turn("You have none. Shall I book one?"))
    await build(session_factory, llm).handle_text(USER, "my appointments?")
    assert _tool_results(llm)[0].code == ResultCode.NONE
    assert "offer to book" in _tool_results(llm)[0].data["next_step"], "E3-S1-AC2: says so and offers to book"


async def test_cancel_shows_confirm_cancel_and_keep_it_then_cancels(session_factory: Factory) -> None:
    doctor, me, _ = await _setup(session_factory)
    appointment = await _book(session_factory, doctor, me, at(8, 9))
    llm = ScriptedLLM(
        call_turn(("cancel_appointment", {"appointment_ref": appointment.ref})), text_turn("Tap below.")
    )
    service = build(session_factory, llm)
    replies = await service.handle_text(USER, f"cancel {appointment.ref}")
    buttons = _buttons(replies)
    assert set(buttons) == {"Confirm cancel", "Keep it"}
    assert appointment.ref in replies[-1].text
    assert await _status(session_factory, appointment) == "booked", "nothing changes before the tap"
    [done] = await service.handle_callback(USER, buttons["Confirm cancel"])
    assert "cancelled" in done.text.lower()
    assert await _status(session_factory, appointment) == "cancelled"


async def test_tapping_confirm_cancel_twice_says_already_cancelled(session_factory: Factory) -> None:
    """E3-S3-AC3: the second tap reports the state; nothing changes."""
    doctor, me, _ = await _setup(session_factory)
    appointment = await _book(session_factory, doctor, me, at(8, 9))
    llm = ScriptedLLM(
        call_turn(("cancel_appointment", {"appointment_ref": appointment.ref})), text_turn("Tap below.")
    )
    service = build(session_factory, llm)
    confirm = _buttons(await service.handle_text(USER, "cancel it"))["Confirm cancel"]
    await service.handle_callback(USER, confirm)
    [again] = await service.handle_callback(USER, confirm)
    assert again.text == f"{appointment.ref} is already cancelled; nothing has changed."
    assert await _status(session_factory, appointment) == "cancelled"


async def test_confirm_cancel_after_keep_it_is_expired_not_already_cancelled(
    session_factory: Factory,
) -> None:
    doctor, me, _ = await _setup(session_factory)
    appointment = await _book(session_factory, doctor, me, at(8, 9))
    llm = ScriptedLLM(
        call_turn(("cancel_appointment", {"appointment_ref": appointment.ref})), text_turn("Tap below.")
    )
    service = build(session_factory, llm)
    buttons = _buttons(await service.handle_text(USER, "cancel it"))
    await service.handle_callback(USER, buttons["Keep it"])
    [late] = await service.handle_callback(USER, buttons["Confirm cancel"])
    assert "expired" in late.text.lower()
    assert await _status(session_factory, appointment) == "booked"


async def test_keep_it_leaves_the_appointment(session_factory: Factory) -> None:
    doctor, me, _ = await _setup(session_factory)
    appointment = await _book(session_factory, doctor, me, at(8, 9))
    llm = ScriptedLLM(
        call_turn(("cancel_appointment", {"appointment_ref": appointment.ref})), text_turn("Tap below.")
    )
    service = build(session_factory, llm)
    keep = _buttons(await service.handle_text(USER, "cancel it"))["Keep it"]
    [reply] = await service.handle_callback(USER, keep)
    assert "kept" in reply.text.lower()
    assert await _status(session_factory, appointment) == "booked"


async def test_cancel_already_cancelled_and_cutoff_are_refused_by_the_tool(session_factory: Factory) -> None:
    doctor, me, _ = await _setup(session_factory)
    soon = await _book(session_factory, doctor, me, at(7, 9, 45))
    async with session_factory() as session:
        gone = await make_appointment(session, doctor=doctor, patient=me, start=at(9, 9), status="cancelled")
        await session.commit()
    llm = ScriptedLLM(
        call_turn(("cancel_appointment", {"appointment_ref": soon.ref})),
        call_turn(("cancel_appointment", {"appointment_ref": gone.ref})),
        text_turn("Sorry."),
    )
    replies = await build(session_factory, llm).handle_text(USER, "cancel both")
    within, already = _tool_results(llm)
    assert within.code == ResultCode.WITHIN_CUTOFF
    assert "+12025550100" in str(within.data)
    assert already.code == ResultCode.ALREADY_CANCELLED
    assert _buttons(replies) == {}


async def test_another_patients_reference_is_not_found(session_factory: Factory) -> None:
    doctor, _, other = await _setup(session_factory)
    theirs = await _book(session_factory, doctor, other, at(8, 9))
    llm = ScriptedLLM(
        call_turn(("cancel_appointment", {"appointment_ref": theirs.ref})), text_turn("Not found.")
    )
    await build(session_factory, llm).handle_text(USER, f"cancel {theirs.ref}")
    assert _tool_results(llm)[0].code == ResultCode.NOT_FOUND
    assert await _status(session_factory, theirs) == "booked"


async def test_reschedule_summary_then_confirm_moves_the_booking(session_factory: Factory) -> None:
    doctor, me, _ = await _setup(session_factory)
    old = await _book(session_factory, doctor, me, at(8, 9))
    new_start = at(9, 10).isoformat()
    llm = ScriptedLLM(
        call_turn(("reschedule_appointment", {"appointment_ref": old.ref, "new_slot_start": new_start})),
        text_turn("Please confirm the change."),
    )
    service = build(session_factory, llm)
    replies = await service.handle_text(USER, "move it to Wednesday 10")
    summary = next(r for r in replies if r.inline_buttons)
    assert "Wednesday, 9 January 2030" in summary.text
    assert "10:00 AM" in summary.text
    assert "Asha Rao" in summary.text
    [done] = await service.handle_callback(USER, _buttons(replies)["Confirm"])
    assert old.ref in done.text
    assert "APT-" in done.text
    assert await _status(session_factory, old) == "cancelled"


async def test_reschedule_slot_taken_keeps_the_old_booking_and_offers_slots(session_factory: Factory) -> None:
    doctor, me, other = await _setup(session_factory)
    old = await _book(session_factory, doctor, me, at(8, 9))
    target = at(9, 10)
    llm = ScriptedLLM(
        call_turn(
            ("reschedule_appointment", {"appointment_ref": old.ref, "new_slot_start": target.isoformat()})
        ),
        text_turn("Confirm?"),
    )
    service = build(session_factory, llm)
    confirm = _buttons(await service.handle_text(USER, "move it"))["Confirm"]
    await _book(session_factory, doctor, other, target)
    [taken] = await service.handle_callback(USER, confirm)
    assert "taken" in taken.text
    assert await _status(session_factory, old) == "booked"
    options = _buttons([taken])
    assert len(options) == 3
    [summary] = await service.handle_callback(USER, next(iter(options.values())))
    [done] = await service.handle_callback(USER, _buttons([summary])["Confirm"])
    assert old.ref in done.text
    assert await _status(session_factory, old) == "cancelled"
