"""Entry points for every patient interaction (agent-design.md: ConversationService).

The Telegram adapter and the evaluation suite call these methods; they hold no transport details.
Every entry point is guarded: whatever fails, the patient gets a reply with the clinic phone number.
"""

from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import Any

import structlog

from clinic.agent.guardrails import is_emergency
from clinic.agent.llm import ModelText, UserText
from clinic.agent.loop import AgentLoop, AgentOutcome
from clinic.agent.memory import ConversationMemory, SessionTracker
from clinic.agent.pending import PendingAction, PendingKind, PendingStore
from clinic.agent.prompt import build_system_prompt
from clinic.agent.tools import AgentServices, ToolContext
from clinic.conversation import registration as reg
from clinic.conversation.appointment_actions import CHANGE, CONFIRM, PICK, AppointmentActions, summary
from clinic.domain.messages import Button, IncomingUser, Reply, callback
from clinic.domain.patients import InvalidNameError, InvalidPhoneError, normalise_name, normalise_phone
from clinic.observability import bind_request_id, new_request_id, request_id_var, safe_exception_fields
from clinic.services.clinic_settings import ClinicSettingsService, ClinicSettingsView
from clinic.services.patients import PatientService, PatientView, PhoneCheck, RegistrationOutcome

log = structlog.get_logger(__name__)

EXPIRED = "This request has expired, please ask again."
DELETE, KEEP = "delete", "keep"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _parse_callback(data: str) -> tuple[str, str]:
    parts = data.split(":", 2)
    if len(parts) != 3 or parts[0] != "v1":
        return "", ""
    return parts[1], parts[2]


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
        sessions: SessionTracker | None = None,
        pending: PendingStore | None = None,
    ) -> None:
        self._patients = patients
        self._settings = settings
        self._agent = agent
        self._memory = memory
        self._services = services
        self._clock = clock
        self._sessions = sessions or SessionTracker()
        self._pending = pending or PendingStore(clock)
        self._registrations = reg.RegistrationStore(clock)
        self._last_view: ClinicSettingsView | None = None
        self._actions = AppointmentActions(
            services=services, patients=patients, pending=self._pending, note=self._note, view=self._view
        )

    # ---- public entry points -------------------------------------------------------------------

    async def handle_text(self, user: IncomingUser, text: str) -> list[Reply]:
        return await self._guarded(lambda: self._text(user, text))

    async def handle_contact(
        self, user: IncomingUser, *, contact_user_id: int | None, phone: str
    ) -> list[Reply]:
        return await self._guarded(lambda: self._contact(user, contact_user_id, phone))

    async def handle_callback(self, user: IncomingUser, data: str) -> list[Reply]:
        return await self._guarded(lambda: self._callback(user, data))

    async def _guarded(self, work: Callable[[], Awaitable[list[Reply]]]) -> list[Reply]:
        with bind_request_id(new_request_id()):
            try:
                return await work()
            except Exception as exc:
                log.error("conversation_failed", **safe_exception_fields(exc))
                return [self._fallback()]

    def _fallback(self) -> Reply:
        phone = f", or call the clinic on {self._last_view.phone}" if self._last_view else ""
        return Reply(f"Sorry, something went wrong on our side. Please try again in a moment{phone}.")

    async def _view(self) -> ClinicSettingsView:
        view = await self._settings.get()
        self._last_view = view
        return view

    # ---- text --------------------------------------------------------------------------------

    async def _text(self, user: IncomingUser, text: str) -> list[Reply]:
        view = await self._view()
        stripped = text.strip()
        patient = await self._patients.get_by_telegram(user.telegram_user_id)
        # E5-S3: first check on every message, registered or not, mid-flow included; no LLM call.
        if is_emergency(stripped, view.emergency_phrases):
            return [await self._emergency(user, patient, view)]
        command = stripped.split()[0].lower() if stripped.startswith("/") else None
        if command == "/deletemydata":
            return [self._delete_request(user, patient)]
        if patient is None:
            return [await self._registration_text(user, stripped, view)]
        replies = []
        if self._sessions.is_new_session(user.telegram_user_id):
            replies.append(Reply(f"Hi {patient.first_name}!"))
        if command == "/start":
            return [*replies, Reply("How can I help you today?")]
        if command is not None:
            return [*replies, self._help(view)]
        staged_before = self._pending.peek(user.telegram_user_id)
        outcome = await self._run_agent(patient, stripped, view)
        replies.append(self._outcome_reply(outcome, view))
        staged = self._pending.peek(user.telegram_user_id)
        if outcome.stopped == "reply" and staged is not None and staged is not staged_before:
            staged_summary = summary(staged, patient)
            if staged_summary is not None:
                replies.append(staged_summary)
        return replies

    @staticmethod
    def _help(view: ClinicSettingsView) -> Reply:
        return Reply(
            "I can show our doctors, find free slots, book appointments and answer questions "
            "about the clinic. "
            f"Commands: /start, /deletemydata. For anything urgent, call {view.phone}."
        )

    async def _registration_text(self, user: IncomingUser, text: str, view: ClinicSettingsView) -> Reply:
        state = self._registrations.get(user.telegram_user_id)
        if state is None or state.step is reg.Step.CONSENT or text.startswith("/"):
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
        self._sessions.mark_seen(user.telegram_user_id)
        log.info("registration_completed", outcome=result.outcome.value)
        return reg.registered(result.patient.first_name)

    # ---- contact -----------------------------------------------------------------------------

    async def _contact(self, user: IncomingUser, contact_user_id: int | None, phone: str) -> list[Reply]:
        view = await self._view()
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

    # ---- buttons -----------------------------------------------------------------------------

    async def _callback(self, user: IncomingUser, data: str) -> list[Reply]:
        view = await self._view()
        if data in (reg.CONSENT_YES, reg.CONSENT_NO):
            return [await self._consent(user, data, view)]
        kind, token = _parse_callback(data)
        if kind in (DELETE, KEEP):
            return [await self._delete_decision(user, kind, token)]
        if kind == CONFIRM:
            return [await self._actions.decide(user, CONFIRM, token)]
        if kind == CHANGE:
            return [await self._actions.decide(user, CHANGE, token)]
        if kind == PICK:
            return [await self._actions.pick(user, token)]
        log.info("callback_expired_or_unknown")
        return [Reply(EXPIRED)]

    async def _consent(self, user: IncomingUser, data: str, view: ClinicSettingsView) -> Reply:
        if await self._patients.get_by_telegram(user.telegram_user_id) is not None:
            return Reply("You're already registered.")
        if data == reg.CONSENT_NO:
            self._registrations.drop(user.telegram_user_id)
            return reg.declined(view)
        state = self._registrations.get(user.telegram_user_id) or self._registrations.start(
            user.telegram_user_id
        )
        state.consented_at = self._clock()
        state.step = reg.Step.PHONE
        return reg.ask_for_phone()

    async def _emergency(
        self, user: IncomingUser, patient: PatientView | None, view: ClinicSettingsView
    ) -> Reply:
        created = await self._services.alerts.raise_emergency(
            patient_id=patient.id if patient else None,
            telegram_user_id=user.telegram_user_id,
            now=self._clock(),
        )
        log.warning("emergency_redirected", new_alert=created)
        return Reply(
            f"This sounds like an emergency. Please call {view.emergency_number} now or go to the nearest "
            "emergency department. This chat cannot help with emergencies. "
            "We have also flagged your message to the clinic staff."
        )

    # ---- data deletion (E1-S4) -----------------------------------------------------------------

    def _delete_request(self, user: IncomingUser, patient: PatientView | None) -> Reply:
        if patient is None:
            self._registrations.drop(user.telegram_user_id)
            return Reply("There is no data stored for this chat, so there is nothing to delete.")
        action = self._pending.put(user.telegram_user_id, "delete_data", {"patient_id": str(patient.id)})
        return Reply(
            "Deleting your data will cancel your upcoming appointments and remove your name and phone number "
            "from our records. Past visits stay only as anonymous records. This cannot be undone. Continue?",
            inline_buttons=(
                (
                    Button("Delete my data", callback(DELETE, action.token)),
                    Button("Keep my data", callback(KEEP, action.token)),
                ),
            ),
        )

    async def _delete_decision(self, user: IncomingUser, kind: str, token: str) -> Reply:
        staged = self._pending.peek(user.telegram_user_id)
        if staged is None or staged.kind != "delete_data":
            return Reply(EXPIRED)
        action = self._pending.pop(user.telegram_user_id, token)
        if action is None:
            return Reply(EXPIRED)
        if kind == KEEP:
            return Reply("Okay, nothing has been changed.")
        patient = await self._patients.get_by_telegram(user.telegram_user_id)
        if patient is None or str(patient.id) != action.params.get("patient_id"):
            return Reply(EXPIRED)
        cancelled = await self._patients.delete_patient(patient.id, now=self._clock())
        self._forget(user.telegram_user_id)
        log.info("patient_data_deleted", cancelled_appointments=cancelled)
        cancelled_text = f" and {cancelled} upcoming appointment(s) cancelled" if cancelled else ""
        return Reply(
            f"Your data has been deleted{cancelled_text}. Send /start if you want to register again.",
            remove_keyboard=True,
        )

    def _note(self, user_id: int, event: str, reply_text: str) -> None:
        """Code-authored outcome kept in memory, so the model knows what the buttons did."""
        self._memory.append(user_id, [UserText(event), ModelText(reply_text, trusted=True)])

    def _forget(self, user_id: int) -> None:
        self._memory.clear(user_id)
        self._sessions.forget(user_id)
        self._pending.discard(user_id)
        self._registrations.drop(user_id)

    # ---- agent ---------------------------------------------------------------------------------

    async def _run_agent(self, patient: PatientView, text: str, view: ClinicSettingsView) -> AgentOutcome:
        today = self._clock().astimezone(view.tz).date()
        request_id = request_id_var.get() or new_request_id()
        user_id = patient.telegram_user_id or 0

        def stage(kind: PendingKind, params: Mapping[str, Any]) -> PendingAction:
            return self._pending.put(user_id, kind, params)

        ctx = ToolContext(patient_id=patient.id, request_id=request_id, services=self._services, stage=stage)
        # D-16: the model sees the clinic configuration and the message text, never who the patient is.
        prompt = build_system_prompt(view, today)
        return await self._agent.run(ctx, self._memory, patient.telegram_user_id or 0, text, prompt)

    @staticmethod
    def _outcome_reply(outcome: AgentOutcome, view: ClinicSettingsView) -> Reply:
        if outcome.stopped == "reply" and outcome.text:
            return Reply(outcome.text)
        if outcome.stopped == "ungrounded":
            return Reply(
                "Sorry, I couldn't confirm that information. Please ask me again, "
                f"or call the clinic on {view.phone}."
            )
        if outcome.stopped == "limit":
            return Reply(
                f"Sorry, I couldn't complete that. Please try rephrasing, or call the clinic on {view.phone}."
            )
        return Reply(
            "Sorry, I can't answer right now. Please try again in a moment, "
            f"or call the clinic on {view.phone}."
        )
