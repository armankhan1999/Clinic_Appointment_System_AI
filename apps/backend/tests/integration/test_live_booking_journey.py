"""Live end-to-end booking through the real Gemini model and the test schema (synthetic data, D-16).

Run explicitly: `uv run pytest -m live tests/integration/test_live_booking_journey.py`.
LLM output varies between runs, so this is a smoke test; the evaluation suite (M6) measures quality.
"""

from datetime import datetime, time
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from clinic.agent.grounding import extract_times
from clinic.agent.llm import GeminiLLM
from clinic.agent.loop import AgentLoop, AuditEntry
from clinic.agent.memory import ConversationMemory
from clinic.agent.tools import build_registry
from clinic.config import Settings
from clinic.conversation.service import ConversationService
from clinic.db.models import Appointment
from clinic.domain.messages import IncomingUser, Reply
from clinic.services.clinic_settings import ClinicSettingsService
from clinic.services.patients import PatientService

from .factories import add_schedule, agent_services, make_clinic_settings, make_doctor, make_patient

pytestmark = pytest.mark.live

Factory = async_sessionmaker[AsyncSession]
IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2030, 1, 7, 8, 0, tzinfo=IST)  # Monday 08:00
USER = IncomingUser(telegram_user_id=4242)


def _buttons(replies: list[Reply]) -> dict[str, str]:
    return {b.text: b.callback_data or "" for r in replies for row in r.inline_buttons for b in row}


async def test_patient_books_through_the_real_model(settings: Settings, session_factory: Factory) -> None:
    async with session_factory() as session:
        await make_clinic_settings(session)
        doctor = await make_doctor(session, name="Dr. Meera Iyer", specialty="General Physician")
        await add_schedule(session, doctor, 2, time(9), time(11))  # Wednesday
        await make_patient(session, telegram_user_id=USER.telegram_user_id, name="Asha Rao")
        await session.commit()
    audit: list[AuditEntry] = []

    async def record(entry: AuditEntry) -> None:
        audit.append(entry)

    llm = GeminiLLM(settings.gemini_api_key, settings.gemini_model, settings.llm_timeout_seconds)
    service = ConversationService(
        patients=PatientService(session_factory),
        settings=ClinicSettingsService(session_factory),
        agent=AgentLoop(llm, build_registry(), record, actor_id=settings.gemini_model, budget_seconds=30),
        memory=ConversationMemory(),
        services=agent_services(session_factory, clock=lambda: NOW),
        clock=lambda: NOW,
    )

    first = await service.handle_text(USER, "Is Dr. Meera Iyer free on Wednesday morning?")
    answer = first[-1].text
    print("\nturn 1:", [e.action for e in audit], "|", answer)
    assert "check_availability" in [e.action for e in audit]
    offered = sorted(extract_times(answer))
    assert offered, f"expected free times in the answer, got: {answer}"
    assert all(9 * 60 <= minute < 11 * 60 for minute in offered)

    chosen = f"{offered[0] // 60}:{offered[0] % 60:02d} AM"
    second = await service.handle_text(USER, f"Please book {chosen}.")
    print("turn 2:", [e.action for e in audit], "|", [r.text for r in second])
    assert "Confirm" in _buttons(second), f"expected a confirmation summary, got: {[r.text for r in second]}"

    [done] = await service.handle_callback(USER, _buttons(second)["Confirm"])
    print("confirm:", done.text)
    assert "APT-" in done.text
    async with session_factory() as session:
        [booked] = (await session.scalars(select(Appointment))).all()
    assert (
        booked.start_time.astimezone(IST).hour * 60 + booked.start_time.astimezone(IST).minute == offered[0]
    )
