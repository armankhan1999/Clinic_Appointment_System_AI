"""Composition root: builds the long-lived objects each process needs from Settings."""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncEngine

from clinic.agent.llm import GeminiLLM
from clinic.agent.loop import AgentLoop, db_audit_writer
from clinic.agent.memory import ConversationMemory
from clinic.agent.tools import AgentServices, build_registry
from clinic.config import DbTarget, Settings
from clinic.conversation.service import ConversationService
from clinic.db.session import make_engine, make_session_factory
from clinic.services.availability import AvailabilityService
from clinic.services.booking import BookingService
from clinic.services.clinic_settings import ClinicSettingsService
from clinic.services.doctors import DoctorService
from clinic.services.patients import PatientService


@dataclass(frozen=True)
class BotRuntime:
    engine: AsyncEngine
    conversation: ConversationService

    async def close(self) -> None:
        await self.engine.dispose()


def build_bot_runtime(settings: Settings) -> BotRuntime:
    engine = make_engine(DbTarget.app(settings), settings)
    session_factory = make_session_factory(engine)
    llm = GeminiLLM(settings.gemini_api_key, settings.gemini_model, settings.llm_timeout_seconds)
    agent = AgentLoop(
        llm,
        build_registry(),
        db_audit_writer(session_factory),
        actor_id=settings.gemini_model,
        budget_seconds=settings.llm_timeout_seconds,
    )
    clinic_settings = ClinicSettingsService(session_factory)
    services = AgentServices(
        doctors=DoctorService(session_factory),
        availability=AvailabilityService(session_factory, clinic_settings),
        booking=BookingService(session_factory, clinic_settings),
    )
    conversation = ConversationService(
        patients=PatientService(session_factory),
        settings=clinic_settings,
        agent=agent,
        memory=ConversationMemory(),
        services=services,
    )
    return BotRuntime(engine=engine, conversation=conversation)
