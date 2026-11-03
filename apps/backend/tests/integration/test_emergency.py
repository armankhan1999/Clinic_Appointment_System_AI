"""Emergency redirect before the LLM (E5-S3-AC1..AC3, IMP-06, NFR-06)."""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from clinic.agent.loop import AgentLoop, AuditEntry
from clinic.agent.memory import ConversationMemory
from clinic.agent.tools import build_registry
from clinic.conversation.service import ConversationService
from clinic.db.models import EmergencyAlert, Patient
from clinic.domain.messages import IncomingUser, Reply
from clinic.services.clinic_settings import ClinicSettingsService
from clinic.services.patients import PatientService

from ..unit.agent_doubles import ScriptedLLM
from .factories import agent_services, make_clinic_settings, make_patient

Factory = async_sessionmaker[AsyncSession]
USER = IncomingUser(telegram_user_id=4242)


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2030, 1, 9, 4, 30, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


async def _no_audit(entry: AuditEntry) -> None:
    return None


async def build(session_factory: Factory, llm: Any, clock: Clock) -> ConversationService:
    async with session_factory() as session:
        await make_clinic_settings(session)
        await session.commit()
    return ConversationService(
        patients=PatientService(session_factory),
        settings=ClinicSettingsService(session_factory),
        agent=AgentLoop(llm, build_registry(), _no_audit, actor_id="test"),
        memory=ConversationMemory(),
        services=agent_services(session_factory),
        clock=clock,
    )


async def _alerts(session_factory: Factory) -> list[EmergencyAlert]:
    async with session_factory() as session:
        return list((await session.scalars(select(EmergencyAlert))).all())


def _callbacks(reply: Reply) -> dict[str, str]:
    return {b.text: b.callback_data or "" for row in reply.inline_buttons for b in row}


async def test_registered_patient_gets_the_fixed_reply_without_the_llm(session_factory: Factory) -> None:
    async with session_factory() as session:
        patient = await make_patient(session, telegram_user_id=USER.telegram_user_id)
        await session.commit()
    llm = ScriptedLLM()
    replies = await (await build(session_factory, llm, Clock())).handle_text(USER, "I have severe chest pain")
    assert "112" in replies[-1].text
    assert "emergency" in replies[-1].text.lower()
    assert llm.transcripts == [], "E5-S3-AC1: the LLM is never called"
    [alert] = await _alerts(session_factory)
    assert (alert.patient_id, alert.telegram_user_id) == (patient.id, USER.telegram_user_id)


async def test_unregistered_sender_is_covered_too(session_factory: Factory) -> None:
    llm = ScriptedLLM()
    [reply] = await (await build(session_factory, llm, Clock())).handle_text(USER, "my father is unconscious")
    assert "112" in reply.text
    [alert] = await _alerts(session_factory)
    assert (alert.patient_id, alert.telegram_user_id) == (None, USER.telegram_user_id)


async def test_emergency_mid_registration_triggers_and_the_flow_continues(session_factory: Factory) -> None:
    service = await build(session_factory, ScriptedLLM(), Clock())
    [welcome] = await service.handle_text(USER, "/start")
    await service.handle_callback(USER, _callbacks(welcome)["I agree"])
    await service.handle_contact(USER, contact_user_id=USER.telegram_user_id, phone="12025550150")
    [emergency] = await service.handle_text(USER, "I can\N{RIGHT SINGLE QUOTATION MARK}t breathe")
    assert "112" in emergency.text
    [done] = await service.handle_text(USER, "Asha Rao")
    assert "registered" in done.text
    async with session_factory() as session:
        assert (await session.scalar(select(Patient))) is not None


async def test_repeated_alerts_from_one_sender_are_deduplicated_for_ten_minutes(
    session_factory: Factory,
) -> None:
    clock = Clock()
    service = await build(session_factory, ScriptedLLM(), clock)
    await service.handle_text(USER, "chest pain")
    clock.now += timedelta(minutes=9)
    await service.handle_text(USER, "chest pain again")
    assert len(await _alerts(session_factory)) == 1
    clock.now += timedelta(minutes=2)
    await service.handle_text(USER, "still chest pain")
    assert len(await _alerts(session_factory)) == 2


def test_alerts_store_no_message_text() -> None:
    columns = {column.key for column in inspect(EmergencyAlert).columns}
    assert columns == {
        "id",
        "patient_id",
        "telegram_user_id",
        "created_at",
        "acknowledged_by",
        "acknowledged_at",
    }
