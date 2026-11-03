"""E1-S4 data deletion, deterministic commands, fallback on failures, identity across tool calls (D-16)."""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from clinic.agent.loop import AgentLoop, AuditEntry
from clinic.agent.memory import ConversationMemory
from clinic.agent.tools import build_registry
from clinic.conversation.service import ConversationService
from clinic.db.models import Appointment, AuditLog, Patient
from clinic.domain.messages import IncomingUser, Reply
from clinic.services.clinic_settings import ClinicSettingsService
from clinic.services.patients import PatientService

from ..unit.agent_doubles import ScriptedLLM, call_turn, text_turn
from .factories import agent_services, make_appointment, make_clinic_settings, make_doctor, make_patient

Factory = async_sessionmaker[AsyncSession]
USER = IncomingUser(telegram_user_id=4242)
NOW = datetime(2030, 1, 9, 4, 30, tzinfo=UTC)


async def _no_audit(entry: AuditEntry) -> None:
    return None


class BrokenPatients(PatientService):
    async def get_by_telegram(self, telegram_user_id: int) -> Any:
        raise ConnectionError("pooler connection reset")


async def build(
    session_factory: Factory, llm: Any, patients: PatientService | None = None
) -> ConversationService:
    async with session_factory() as session:
        await make_clinic_settings(session)
        await session.commit()
    settings = ClinicSettingsService(session_factory)
    return ConversationService(
        patients=patients or PatientService(session_factory),
        settings=settings,
        agent=AgentLoop(llm, build_registry(), _no_audit, actor_id="test"),
        memory=ConversationMemory(),
        services=agent_services(session_factory),
        clock=lambda: NOW,
    )


def _callbacks(reply: Reply) -> dict[str, str]:
    return {b.text: b.callback_data or "" for row in reply.inline_buttons for b in row}


async def _registered_with_appointments(session_factory: Factory) -> tuple[Patient, Appointment, Appointment]:
    async with session_factory() as session:
        patient = await make_patient(session, telegram_user_id=USER.telegram_user_id, name="Asha Rao")
        doctor = await make_doctor(session)
        past = await make_appointment(session, doctor=doctor, patient=patient, start=NOW - timedelta(days=2))
        future = await make_appointment(
            session, doctor=doctor, patient=patient, start=NOW + timedelta(days=2)
        )
        await session.commit()
    return patient, past, future


async def test_deletemydata_explains_and_asks_for_confirmation(session_factory: Factory) -> None:
    await _registered_with_appointments(session_factory)
    llm = ScriptedLLM()
    service = await build(session_factory, llm)
    replies = await service.handle_text(USER, "/deletemydata")
    reply = replies[-1]
    assert "cancel your upcoming appointments" in reply.text
    assert set(_callbacks(reply)) == {"Delete my data", "Keep my data"}
    assert llm.transcripts == [], "commands are handled by code, never by the LLM"


async def test_confirmed_deletion_cancels_future_appointments_and_anonymises(
    session_factory: Factory,
) -> None:
    patient, past, future = await _registered_with_appointments(session_factory)
    service = await build(session_factory, ScriptedLLM())
    replies = await service.handle_text(USER, "/deletemydata")
    [done] = await service.handle_callback(USER, _callbacks(replies[-1])["Delete my data"])
    assert "deleted" in done.text
    async with session_factory() as session:
        stored = await session.get_one(Patient, patient.id)
        statuses = {a.id: a.status for a in (await session.scalars(select(Appointment))).all()}
        audit = await session.scalar(select(AuditLog).where(AuditLog.action == "patient.delete"))
    assert (stored.full_name, stored.phone, stored.telegram_user_id) == ("Deleted patient", None, None)
    assert stored.deleted_at is not None
    assert statuses == {past.id: "booked", future.id: "cancelled"}
    assert audit is not None
    assert audit.args_json == {"cancelled_appointments": 1}


async def test_deleted_patient_is_treated_as_a_new_user(session_factory: Factory) -> None:
    await _registered_with_appointments(session_factory)
    service = await build(session_factory, ScriptedLLM())
    replies = await service.handle_text(USER, "/deletemydata")
    await service.handle_callback(USER, _callbacks(replies[-1])["Delete my data"])
    [again] = await service.handle_text(USER, "hello")
    assert "I agree" in _callbacks(again)


async def test_keeping_data_changes_nothing(session_factory: Factory) -> None:
    patient, _, _ = await _registered_with_appointments(session_factory)
    service = await build(session_factory, ScriptedLLM())
    replies = await service.handle_text(USER, "/deletemydata")
    [kept] = await service.handle_callback(USER, _callbacks(replies[-1])["Keep my data"])
    assert "nothing has been changed" in kept.text.lower()
    async with session_factory() as session:
        assert (await session.get_one(Patient, patient.id)).deleted_at is None


async def test_deletion_button_cannot_be_used_by_someone_else(session_factory: Factory) -> None:
    patient, _, _ = await _registered_with_appointments(session_factory)
    service = await build(session_factory, ScriptedLLM())
    replies = await service.handle_text(USER, "/deletemydata")
    [reply] = await service.handle_callback(IncomingUser(999), _callbacks(replies[-1])["Delete my data"])
    assert "expired" in reply.text
    async with session_factory() as session:
        assert (await session.get_one(Patient, patient.id)).deleted_at is None


async def test_unregistered_user_has_no_data_to_delete(session_factory: Factory) -> None:
    service = await build(session_factory, ScriptedLLM())
    [reply] = await service.handle_text(USER, "/deletemydata")
    assert "no data" in reply.text.lower()


async def test_unexpected_failure_still_answers_with_the_clinic_phone(session_factory: Factory) -> None:
    service = await build(session_factory, ScriptedLLM(), patients=BrokenPatients(session_factory))
    [reply] = await service.handle_text(USER, "hello")
    assert "+12025550100" in reply.text
    [callback_reply] = await service.handle_callback(USER, "v1:consent:yes")
    assert "+12025550100" in callback_reply.text


async def test_identity_stays_out_of_the_llm_across_a_tool_round_trip(session_factory: Factory) -> None:
    async with session_factory() as session:
        await make_patient(
            session, telegram_user_id=USER.telegram_user_id, name="Asha Rao", phone="+12025550150"
        )
        await make_doctor(session, name="Dr. Skin", specialty="Dermatologist")
        await session.commit()
    llm = ScriptedLLM(call_turn(("list_doctors", {})), text_turn("We have Dr. Skin."))
    service = await build(session_factory, llm)
    await service.handle_text(USER, "which doctors?")
    seen = repr(llm.systems) + repr(llm.transcripts)
    assert "Dr. Skin" in seen, "the tool result reached the model"
    for secret in ("Asha", "Rao", "2025550150", "4242"):
        assert secret not in seen
