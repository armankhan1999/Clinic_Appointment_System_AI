"""Patient conversations: E1-S1 start, E1-S2 register, E1-S3 consent, GAP-04, GAP-17, GAP-37, D-16."""

import time
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from clinic.agent.loop import AgentLoop, AuditEntry
from clinic.agent.memory import ConversationMemory
from clinic.agent.tools import AgentServices, build_registry
from clinic.conversation.replies import IncomingUser, Reply
from clinic.conversation.service import ConversationService
from clinic.db.models import HandoffTicket, Patient
from clinic.services.availability import AvailabilityService
from clinic.services.clinic_settings import ClinicSettingsService
from clinic.services.doctors import DoctorService
from clinic.services.patients import PatientService

from ..unit.agent_doubles import UNAVAILABLE, ScriptedLLM, SlowLLM, text_turn
from .factories import make_clinic_settings, make_doctor, make_patient

Factory = async_sessionmaker[AsyncSession]
USER = IncomingUser(telegram_user_id=4242)
PHONE_DIGITS = "12025550150"  # Telegram sends contacts without the plus sign
NOW = datetime(2030, 1, 9, 4, 30, tzinfo=UTC)


async def _no_audit(entry: AuditEntry) -> None:
    return None


async def build(session_factory: Factory, llm: Any, *, budget: float = 8.0) -> ConversationService:
    async with session_factory() as session:
        await make_clinic_settings(session)
        await session.commit()
    agent = AgentLoop(llm, build_registry(), _no_audit, actor_id="test", budget_seconds=budget)
    return ConversationService(
        patients=PatientService(session_factory),
        settings=ClinicSettingsService(session_factory),
        agent=agent,
        memory=ConversationMemory(),
        services=AgentServices(
            doctors=DoctorService(session_factory),
            availability=AvailabilityService(session_factory, ClinicSettingsService(session_factory)),
        ),
        clock=lambda: NOW,
    )


async def _patients(session_factory: Factory) -> int:
    async with session_factory() as session:
        return int(await session.scalar(select(func.count()).select_from(Patient)) or 0)


def _callbacks(reply: Reply) -> dict[str, str]:
    return {b.text: b.callback_data or "" for row in reply.inline_buttons for b in row}


async def _consent_and_share(service: ConversationService) -> None:
    [welcome] = await service.handle_text(USER, "/start")
    await service.handle_callback(USER, _callbacks(welcome)["I agree"])
    await service.handle_contact(USER, contact_user_id=USER.telegram_user_id, phone=PHONE_DIGITS)


async def test_start_shows_welcome_scope_and_consent_before_anything_is_stored(
    session_factory: Factory,
) -> None:
    service = await build(session_factory, ScriptedLLM())
    [reply] = await service.handle_text(USER, "/start")
    assert "Demo Family Clinic" in reply.text
    assert "appointments" in reply.text
    assert "medical advice" in reply.text
    for stored in ("name", "phone number", "appointments", "/deletemydata"):
        assert stored in reply.text
    assert set(_callbacks(reply)) == {"I agree", "No thanks"}
    assert reply.contact_button is None, "consent comes before the Share phone button (D-09)"
    assert await _patients(session_factory) == 0


async def test_no_thanks_stores_nothing_and_shares_the_clinic_phone(session_factory: Factory) -> None:
    service = await build(session_factory, ScriptedLLM())
    [welcome] = await service.handle_text(USER, "hello")
    [reply] = await service.handle_callback(USER, _callbacks(welcome)["No thanks"])
    assert "+12025550100" in reply.text
    assert await _patients(session_factory) == 0
    [again] = await service.handle_text(USER, "hello again")
    assert "I agree" in _callbacks(again)


async def test_i_agree_shows_the_share_phone_button(session_factory: Factory) -> None:
    service = await build(session_factory, ScriptedLLM())
    [welcome] = await service.handle_text(USER, "/start")
    [reply] = await service.handle_callback(USER, _callbacks(welcome)["I agree"])
    assert reply.contact_button is not None
    assert reply.contact_button.request_contact


async def test_contact_of_someone_else_is_rejected(session_factory: Factory) -> None:
    service = await build(session_factory, ScriptedLLM())
    [welcome] = await service.handle_text(USER, "/start")
    await service.handle_callback(USER, _callbacks(welcome)["I agree"])
    for other in (999, None):
        [reply] = await service.handle_contact(USER, contact_user_id=other, phone=PHONE_DIGITS)
        assert "your own" in reply.text
        assert reply.contact_button is not None
    assert await _patients(session_factory) == 0


async def test_contact_before_consent_is_not_used(session_factory: Factory) -> None:
    service = await build(session_factory, ScriptedLLM())
    [reply] = await service.handle_contact(USER, contact_user_id=USER.telegram_user_id, phone=PHONE_DIGITS)
    assert "I agree" in _callbacks(reply)
    assert await _patients(session_factory) == 0


async def test_typing_instead_of_sharing_asks_for_the_button_again(session_factory: Factory) -> None:
    service = await build(session_factory, ScriptedLLM())
    [welcome] = await service.handle_text(USER, "/start")
    await service.handle_callback(USER, _callbacks(welcome)["I agree"])
    [reply] = await service.handle_text(USER, "+1 202 555 0150")
    assert reply.contact_button is not None


async def test_registration_completes_with_consent_time_after_a_valid_name(session_factory: Factory) -> None:
    service = await build(session_factory, ScriptedLLM())
    await _consent_and_share(service)
    assert await _patients(session_factory) == 0, "nothing is stored until the flow completes"
    for bad in ("A", "R2D2", "x" * 61):
        [reply] = await service.handle_text(USER, bad)
        assert "2 to 60" in reply.text
    [done] = await service.handle_text(USER, "  Asha   Rao ")
    assert "Asha" in done.text
    assert done.remove_keyboard
    async with session_factory() as session:
        patient = await session.scalar(select(Patient))
    assert patient is not None
    assert (patient.full_name, patient.phone, patient.telegram_user_id) == ("Asha Rao", "+12025550150", 4242)
    assert patient.consent_at == NOW


async def test_phone_linked_to_another_account_is_not_linked_and_offers_staff(
    session_factory: Factory,
) -> None:
    async with session_factory() as session:
        owner = await make_patient(session, phone="+12025550150", telegram_user_id=999)
        await session.commit()
    service = await build(session_factory, ScriptedLLM())
    [welcome] = await service.handle_text(USER, "/start")
    await service.handle_callback(USER, _callbacks(welcome)["I agree"])
    [reply] = await service.handle_contact(USER, contact_user_id=USER.telegram_user_id, phone=PHONE_DIGITS)
    assert "+12025550100" in reply.text
    assert "Monday to Saturday" in reply.text
    async with session_factory() as session:
        tickets = (await session.scalars(select(HandoffTicket))).all()
        patients = (await session.scalars(select(Patient))).all()
    assert [t.patient_id for t in tickets] == [owner.id]
    assert [p.telegram_user_id for p in patients] == [999]


async def test_registered_patient_is_greeted_once_per_session_and_reaches_the_agent(
    session_factory: Factory,
) -> None:
    async with session_factory() as session:
        await make_patient(session, telegram_user_id=USER.telegram_user_id, name="Asha Rao")
        await make_doctor(session, name="Dr. Skin", specialty="Dermatologist")
        await session.commit()
    llm = ScriptedLLM(text_turn("We have Dr. Skin."), text_turn("Anything else?"))
    service = await build(session_factory, llm)
    first = await service.handle_text(USER, "which doctors?")
    assert [r.text for r in first] == ["Hi Asha!", "We have Dr. Skin."]
    second = await service.handle_text(USER, "thanks")
    assert [r.text for r in second] == ["Anything else?"]


async def test_the_llm_never_sees_the_patients_identity(session_factory: Factory) -> None:
    async with session_factory() as session:
        await make_patient(
            session, telegram_user_id=USER.telegram_user_id, name="Asha Rao", phone="+12025550150"
        )
        await session.commit()
    llm = ScriptedLLM(text_turn("ok"))
    service = await build(session_factory, llm)
    await service.handle_text(USER, "hello")
    seen = repr(llm.systems) + repr(llm.transcripts)
    for secret in ("Asha", "Rao", "2025550150", "4242"):
        assert secret not in seen


async def test_llm_outage_gives_a_fallback_with_the_clinic_phone_quickly(session_factory: Factory) -> None:
    async with session_factory() as session:
        await make_patient(session, telegram_user_id=USER.telegram_user_id)
        await session.commit()
    service = await build(session_factory, ScriptedLLM(UNAVAILABLE))
    replies = await service.handle_text(USER, "hello")
    assert "+12025550100" in replies[-1].text


async def test_slow_llm_is_cut_off_by_the_budget(session_factory: Factory) -> None:
    async with session_factory() as session:
        await make_patient(session, telegram_user_id=USER.telegram_user_id)
        await session.commit()
    service = await build(session_factory, SlowLLM(30), budget=0.3)
    started = time.monotonic()
    replies = await service.handle_text(USER, "hello")
    assert time.monotonic() - started < 10
    assert "+12025550100" in replies[-1].text


async def test_unknown_or_stale_button_is_answered_safely(session_factory: Factory) -> None:
    service = await build(session_factory, ScriptedLLM())
    for data in ("v1:confirm:deadbeef", "garbage", "v1:consent:maybe"):
        [reply] = await service.handle_callback(USER, data)
        assert "expired" in reply.text
