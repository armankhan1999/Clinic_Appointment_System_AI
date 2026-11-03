"""Registration state (consent → phone → name), held in memory only until it completes (E1-S3-AC2, NFR-07)."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from clinic.conversation.replies import Button, Reply, callback
from clinic.domain.patients import NAME_MAX, NAME_MIN
from clinic.services.clinic_settings import ClinicSettingsView

CONSENT_YES = callback("consent", "yes")
CONSENT_NO = callback("consent", "no")
STATE_TTL = timedelta(hours=1)


class Step(StrEnum):
    CONSENT = "consent"
    PHONE = "phone"
    NAME = "name"


@dataclass
class RegistrationState:
    step: Step
    started_at: datetime
    consented_at: datetime | None = None
    phone: str | None = None


class RegistrationStore:
    """Abandoned flows expire after STATE_TTL so memory cannot grow without bound."""

    def __init__(self, clock: Callable[[], datetime]) -> None:
        self._clock = clock
        self._states: dict[int, RegistrationState] = {}

    def get(self, user_id: int) -> RegistrationState | None:
        state = self._states.get(user_id)
        if state is not None and self._clock() - state.started_at > STATE_TTL:
            del self._states[user_id]
            return None
        return state

    def start(self, user_id: int) -> RegistrationState:
        state = RegistrationState(Step.CONSENT, self._clock())
        self._states[user_id] = state
        return state

    def drop(self, user_id: int) -> None:
        self._states.pop(user_id, None)


SHARE_PHONE = Button("Share phone number", request_contact=True)


def welcome_and_consent(view: ClinicSettingsView) -> Reply:
    text = (
        f"Welcome to {view.clinic_name}! I can help you book, change or cancel appointments and answer "
        "questions about the clinic. I can't give medical advice, and please don't share health "
        "details here.\n\n"
        "Before we start: to manage your bookings we store your name, your phone number and your "
        "appointments. We use them only for your appointments and reminders. "
        "You can delete your data at any time with /deletemydata. Do you agree?"
    )
    return Reply(text, inline_buttons=((Button("I agree", CONSENT_YES), Button("No thanks", CONSENT_NO)),))


def declined(view: ClinicSettingsView) -> Reply:
    return Reply(
        f"No problem. Nothing has been saved. If you'd like to book by phone, call us on {view.phone}.",
        remove_keyboard=True,
    )


def ask_for_phone() -> Reply:
    return Reply(
        "Thank you. Please tap 'Share phone number' below so I can link your number to this chat.",
        contact_button=SHARE_PHONE,
    )


def remind_to_use_button() -> Reply:
    return Reply(
        "Please use the 'Share phone number' button below so I can verify your number.",
        contact_button=SHARE_PHONE,
    )


def reject_foreign_contact() -> Reply:
    return Reply("Please share your own phone number using the button below.", contact_button=SHARE_PHONE)


def reject_invalid_phone() -> Reply:
    return Reply(
        "That number doesn't look valid. Please share your own phone number using the button below.",
        contact_button=SHARE_PHONE,
    )


def phone_conflict(view: ClinicSettingsView) -> Reply:
    return Reply(
        "This phone number is already linked to another Telegram account, so I can't link it here. "
        f"I've asked our staff to help. You can also call us on {view.phone} ({view.staff_hours_text}).",
        remove_keyboard=True,
    )


def ask_for_name() -> Reply:
    return Reply("Thanks! Now please type your full name.", remove_keyboard=True)


def invalid_name() -> Reply:
    return Reply(f"Please enter your full name using {NAME_MIN} to {NAME_MAX} letters, without numbers.")


def registered(first_name: str) -> Reply:
    return Reply(
        f"Thanks, {first_name}! You're registered. You can ask me which doctors we have, "
        "book an appointment, or ask about clinic timings, fees and the address.",
        remove_keyboard=True,
    )
