"""Entry points for every patient interaction (agent-design.md: ConversationService).

The Telegram adapter and the evaluation suite call these methods; they hold no transport details.
"""

from collections.abc import Callable
from datetime import UTC, datetime

import structlog

from clinic.agent.loop import AgentLoop, AgentOutcome
from clinic.agent.memory import ConversationMemory
from clinic.agent.prompt import build_system_prompt
from clinic.agent.tools import AgentServices, ToolContext
from clinic.conversation import registration as reg
from clinic.conversation.replies import IncomingUser, Reply
from clinic.domain.patients import InvalidNameError, InvalidPhoneError, normalise_name, normalise_phone
from clinic.observability import bind_request_id, new_request_id
from clinic.services.clinic_settings import ClinicSettingsService, ClinicSettingsView
from clinic.services.patients import PatientService, PatientView, PhoneCheck, RegistrationOutcome

log = structlog.get_logger(__name__)

EXPIRED = "This request has expired, please ask again."


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ConversationService:
    def __init__(
        self,
        *,
        patients: PatientService,
        settings: ClinicSettingsService,
        agent: AgentLoop,
        memory: ConversationMemory,
        services: AgentServices,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._patients = patients
        self._settings = settings
        self._agent = agent
        self._memory = memory
        self._services = services
        self._clock = clock
        self._registrations = reg.RegistrationStore(clock)
        self._greeted: set[int] = set()

    async def handle_text(self, user: IncomingUser, text: str) -> list[Reply]:
        with bind_request_id(new_request_id()) as request_id:
            view = await self._settings.get()
            patient = await self._patients.get_by_telegram(user.telegram_user_id)
            if patient is None:
                return [await self._registration_text(user, text.strip(), view)]
            replies = []
            if user.telegram_user_id not in self._greeted:
                self._greeted.add(user.telegram_user_id)
                replies.append(Reply(f"Hi {patient.first_name}!"))
            if text.strip() == "/start":
                return (
                    [*replies, Reply("How can I help you today?")] if replies else [Reply("How can I help?")]
                )
            outcome = await self._run_agent(patient, text, view, request_id)
            replies.append(self._outcome_reply(outcome, view))
            return replies

    async def handle_contact(
        self, user: IncomingUser, *, contact_user_id: int | None, phone: str
    ) -> list[Reply]:
        with bind_request_id(new_request_id()):
            view = await self._settings.get()
            patient = await self._patients.get_by_telegram(user.telegram_user_id)
            if patient is not None:
                return [Reply(f"You're already registered, {patient.first_name}.", remove_keyboard=True)]
            state = self._registrations.get(user.telegram_user_id)
            if state is None or state.consented_at is None:
                self._registrations.start(user.telegram_user_id)
                return [reg.welcome_and_consent(view)]
            if contact_user_id is None or contact_user_id != user.telegram_user_id:
                log.info("registration_contact_rejected", reason="not_own_contact")
                return [reg.reject_foreign_contact()]
            try:
                normalised = normalise_phone(phone)
            except InvalidPhoneError:
                return [reg.reject_invalid_phone()]
            check = await self._patients.check_phone(normalised, telegram_user_id=user.telegram_user_id)
            if check is PhoneCheck.LINKED_ELSEWHERE:
                await self._patients.flag_phone_conflict(normalised)
                self._registrations.drop(user.telegram_user_id)
                return [reg.phone_conflict(view)]
            state.phone = normalised
            state.step = reg.Step.NAME
            return [reg.ask_for_name()]

    async def handle_callback(self, user: IncomingUser, data: str) -> list[Reply]:
        with bind_request_id(new_request_id()):
            view = await self._settings.get()
            if data in (reg.CONSENT_YES, reg.CONSENT_NO):
                if await self._patients.get_by_telegram(user.telegram_user_id) is not None:
                    return [Reply("You're already registered.")]
                if data == reg.CONSENT_NO:
                    self._registrations.drop(user.telegram_user_id)
                    return [reg.declined(view)]
                state = self._registrations.get(user.telegram_user_id) or self._registrations.start(
                    user.telegram_user_id
                )
                state.consented_at = self._clock()
                state.step = reg.Step.PHONE
                return [reg.ask_for_phone()]
            log.info("callback_expired_or_unknown")
            return [Reply(EXPIRED)]

    async def _registration_text(self, user: IncomingUser, text: str, view: ClinicSettingsView) -> Reply:
        state = self._registrations.get(user.telegram_user_id)
        if state is None or state.step is reg.Step.CONSENT or text == "/start":
            self._registrations.start(user.telegram_user_id)
            return reg.welcome_and_consent(view)
        if state.step is reg.Step.PHONE:
            return reg.remind_to_use_button()
        try:
            full_name = normalise_name(text)
        except InvalidNameError:
            return reg.invalid_name()
        if state.phone is None or state.consented_at is None:
            self._registrations.start(user.telegram_user_id)
            return reg.welcome_and_consent(view)
        result = await self._patients.register_from_telegram(
            telegram_user_id=user.telegram_user_id,
            phone=state.phone,
            full_name=full_name,
            consented_at=state.consented_at,
        )
        self._registrations.drop(user.telegram_user_id)
        if result.outcome is RegistrationOutcome.LINKED_ELSEWHERE or result.patient is None:
            return reg.phone_conflict(view)
        self._greeted.add(user.telegram_user_id)
        log.info("registration_completed", outcome=result.outcome.value)
        return reg.registered(result.patient.first_name)

    async def _run_agent(
        self, patient: PatientView, text: str, view: ClinicSettingsView, request_id: str
    ) -> AgentOutcome:
        today = self._clock().astimezone(view.tz).date()
        ctx = ToolContext(patient_id=patient.id, request_id=request_id, services=self._services)
        # D-16: the model sees the clinic configuration and the message text, never who the patient is.
        prompt = build_system_prompt(view, today)
        return await self._agent.run(ctx, self._memory, patient.telegram_user_id or 0, text, prompt)

    @staticmethod
    def _outcome_reply(outcome: AgentOutcome, view: ClinicSettingsView) -> Reply:
        if outcome.stopped == "reply" and outcome.text:
            return Reply(outcome.text)
        if outcome.stopped == "limit":
            return Reply(
                f"Sorry, I couldn't complete that. Please try rephrasing, or call the clinic on {view.phone}."
            )
        return Reply(
            "Sorry, I can't answer right now. Please try again in a moment, "
            f"or call the clinic on {view.phone}."
        )
