"""Confirm/Change handling for staged appointment changes (AGT-11, E2-S3, E3-S2, E3-S3, GAP-34).

Summaries are rendered here by code, so the patient's name never passes through the LLM (D-16). Every
write happens only after the same patient taps the button carrying the single-use token.
"""

from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
from typing import Any, Final, Literal
from uuid import UUID

from clinic.agent.pending import PendingAction, PendingStore
from clinic.agent.tools import AgentServices
from clinic.conversation.replies import Button, IncomingUser, Reply, callback
from clinic.domain.results import ResultCode
from clinic.domain.slots import Slot, format_date_long, format_time_12h
from clinic.services.clinic_settings import ClinicSettingsView
from clinic.services.patients import PatientService, PatientView

CONFIRM: Final = "confirm"
CHANGE: Final = "change"
PICK: Final = "pick"
EXPIRED = "This request has expired, please ask again."
STAGED_CHANGES = frozenset({"book", "reschedule", "cancel"})

type Note = Callable[[int, str, str], None]
type ViewGetter = Callable[[], Awaitable[ClinicSettingsView]]


def _buttons(action: PendingAction, confirm_label: str, change_label: str) -> tuple[tuple[Button, ...], ...]:
    return (
        (
            Button(confirm_label, callback(CONFIRM, action.token)),
            Button(change_label, callback(CHANGE, action.token)),
        ),
    )


def summary(action: PendingAction, patient: PatientView) -> Reply | None:
    """The code-rendered summary for a staged change, or None when nothing is staged for confirmation."""
    p = action.params
    if action.kind == "book":
        return Reply(
            "Please confirm your appointment:\n"
            f"Doctor: {p['doctor']}\nDate: {p['date']}\nTime: {p['time']}\nPatient: {patient.full_name}",
            inline_buttons=_buttons(action, "Confirm", "Change"),
        )
    if action.kind == "reschedule":
        return Reply(
            f"Please confirm the change to {p['reference']}:\nDoctor: {p['doctor']}\n"
            f"From: {p['old_date']} at {p['old_time']}\nTo: {p['date']} at {p['time']}\n"
            f"Patient: {patient.full_name}",
            inline_buttons=_buttons(action, "Confirm", "Change"),
        )
    if action.kind == "cancel":
        return Reply(
            f"Please confirm the cancellation:\nReference: {p['reference']}\nDoctor: {p['doctor']}\n"
            f"Date: {p['date']}\nTime: {p['time']}\nPatient: {patient.full_name}",
            inline_buttons=_buttons(action, "Confirm cancel", "Keep it"),
        )
    return None


class AppointmentActions:
    def __init__(
        self,
        *,
        services: AgentServices,
        patients: PatientService,
        pending: PendingStore,
        note: Note,
        view: ViewGetter,
    ) -> None:
        self._services = services
        self._patients = patients
        self._pending = pending
        self._note = note
        self._view = view

    async def decide(self, user: IncomingUser, button: Literal["confirm", "change"], token: str) -> Reply:
        staged = self._pending.peek(user.telegram_user_id)
        if staged is None or staged.kind not in STAGED_CHANGES:
            return Reply(EXPIRED)
        action = self._pending.pop(user.telegram_user_id, token)
        if action is None:
            return Reply(EXPIRED)
        if button == CHANGE:
            return self._declined(user, action)
        patient = await self._patients.get_by_telegram(user.telegram_user_id)
        if patient is None:
            return Reply(EXPIRED)
        if action.kind == "book":
            return await self._confirm_booking(user, patient, action)
        if action.kind == "reschedule":
            return await self._confirm_reschedule(user, patient, action)
        return await self._confirm_cancel(user, patient, action)

    def _declined(self, user: IncomingUser, action: PendingAction) -> Reply:
        if action.kind == "cancel":
            text = f"Okay, your appointment {action.params['reference']} is kept."
        elif action.kind == "reschedule":
            text = "No problem, your appointment is unchanged. Which day or time would you prefer?"
        else:
            text = "No problem, nothing has been booked. Which day or time would you prefer?"
        self._note(user.telegram_user_id, "(The patient declined the change.)", text)
        return Reply(text)

    async def _too_close(self) -> str:
        view = await self._view()
        return (
            "It's now too close to the appointment to change it here. "
            f"Please call the clinic on {view.phone}."
        )

    async def _confirm_booking(
        self, user: IncomingUser, patient: PatientView, action: PendingAction
    ) -> Reply:
        p = action.params
        outcome = await self._services.booking.book(
            patient_id=patient.id,  # E2-S3-AC5: from the session, never from the model
            doctor_id=UUID(p["doctor_id"]),
            slot_start=datetime.fromisoformat(p["slot_start"]),
            source="bot",
        )
        if outcome.code is ResultCode.OK:
            text = (
                f"Booked! Your reference is {outcome.reference}: {p['doctor']} on {p['date']} at {p['time']}."
            )
            self._note(user.telegram_user_id, "(The patient tapped Confirm.)", text)
            return Reply(text)
        if outcome.code is ResultCode.SLOT_TAKEN and outcome.alternatives:
            return await self._offer_alternatives(user, p, outcome.alternatives, {"mode": "book"})
        reason = (
            "you have reached the booking limit"
            if outcome.code is ResultCode.LIMIT_REACHED
            else "that time is no longer available"
        )
        text = f"Sorry, I couldn't book it because {reason}. Please ask me for other free times."
        self._note(user.telegram_user_id, "(The patient tapped Confirm.)", text)
        return Reply(text)

    async def _confirm_reschedule(
        self, user: IncomingUser, patient: PatientView, action: PendingAction
    ) -> Reply:
        p = action.params
        outcome = await self._services.booking.reschedule(
            patient_id=patient.id,
            appointment_id=UUID(p["appointment_id"]),
            new_slot_start=datetime.fromisoformat(p["new_slot_start"]),
        )
        if outcome.code is ResultCode.OK:
            text = (
                f"Done! {outcome.old_reference} is moved to {p['doctor']} on {p['date']} at {p['time']}. "
                f"Your new reference is {outcome.reference}."
            )
        elif outcome.code is ResultCode.SLOT_TAKEN and outcome.alternatives:
            extra = {k: p[k] for k in ("appointment_id", "reference", "old_date", "old_time")}
            return await self._offer_alternatives(
                user, p, outcome.alternatives, {"mode": "reschedule", **extra}
            )
        elif outcome.code is ResultCode.WITHIN_CUTOFF:
            text = await self._too_close()
        else:
            text = (
                "Sorry, I couldn't move it because that time is no longer available. "
                "Your appointment is unchanged."
            )
        self._note(user.telegram_user_id, "(The patient tapped Confirm.)", text)
        return Reply(text)

    async def _confirm_cancel(self, user: IncomingUser, patient: PatientView, action: PendingAction) -> Reply:
        p = action.params
        outcome = await self._services.booking.cancel(
            patient_id=patient.id, appointment_id=UUID(p["appointment_id"])
        )
        if outcome.code is ResultCode.OK:
            text = (
                f"Cancelled: {p['reference']} with {p['doctor']} on {p['date']} at {p['time']}. "
                "The slot is free again."
            )
        elif outcome.code is ResultCode.ALREADY_CANCELLED:
            text = f"{p['reference']} is already cancelled; nothing has changed."  # E3-S3-AC3
        elif outcome.code is ResultCode.WITHIN_CUTOFF:
            text = await self._too_close()
        else:
            text = EXPIRED
        self._note(user.telegram_user_id, "(The patient tapped Confirm cancel.)", text)
        return Reply(text)

    async def _offer_alternatives(
        self, user: IncomingUser, p: Mapping[str, Any], alternatives: tuple[Slot, ...], extra: dict[str, str]
    ) -> Reply:
        """E2-S3-AC3, E3-S2-AC3: the nearest free slots as buttons that lead to a fresh summary."""
        view = await self._view()
        requested = datetime.fromisoformat(str(p.get("slot_start") or p.get("new_slot_start"))).astimezone(
            view.tz
        )
        choices = []
        for slot in alternatives:
            local = slot.start.astimezone(view.tz)
            label = format_time_12h(local)
            if local.date() != requested.date():
                label = f"{format_date_long(local.date())}, {label}"
            choices.append((label, slot.start.isoformat()))
        choose = self._pending.put(
            user.telegram_user_id,
            "choose_slot",
            {
                "doctor_id": p["doctor_id"],
                "doctor": p["doctor"],
                "slots": [iso for _, iso in choices],
                **extra,
            },
        )
        text = f"Sorry, that slot was just taken. The nearest free times with {p['doctor']} are:"
        self._note(
            user.telegram_user_id,
            "(The patient tapped Confirm.)",
            f"{text} {', '.join(label for label, _ in choices)}.",
        )
        return Reply(
            text,
            inline_buttons=tuple(
                (Button(label, callback(PICK, f"{choose.token}:{index}")),)
                for index, (label, _) in enumerate(choices)
            ),
        )

    async def pick(self, user: IncomingUser, value: str) -> Reply:
        token, _, index_text = value.rpartition(":")
        staged = self._pending.peek(user.telegram_user_id)
        if staged is None or staged.kind != "choose_slot":
            return Reply(EXPIRED)
        action = self._pending.pop(user.telegram_user_id, token)
        if action is None or not index_text.isdigit() or int(index_text) >= len(action.params["slots"]):
            return Reply(EXPIRED)
        patient = await self._patients.get_by_telegram(user.telegram_user_id)
        if patient is None:
            return Reply(EXPIRED)
        view = await self._view()
        p = action.params
        doctor_id = UUID(p["doctor_id"])
        slot_start = datetime.fromisoformat(p["slots"][int(index_text)])
        moving = p.get("mode") == "reschedule"
        check = await self._services.booking.precheck(
            patient.id,
            doctor_id,
            slot_start,
            exclude_appointment_id=UUID(p["appointment_id"]) if moving else None,
        )
        if check.code is not ResultCode.OK or check.slot is None:
            return Reply("Sorry, that time is no longer free. Please ask me for other free times.")
        local = check.slot.start.astimezone(view.tz)
        when = {
            "doctor": check.doctor_name,
            "date": format_date_long(local.date()),
            "time": format_time_12h(local),
        }
        if moving:
            staged_change = self._pending.put(
                user.telegram_user_id,
                "reschedule",
                {
                    "appointment_id": p["appointment_id"],
                    "reference": p["reference"],
                    "old_date": p["old_date"],
                    "old_time": p["old_time"],
                    "doctor_id": str(doctor_id),
                    "new_slot_start": check.slot.start.isoformat(),
                    **when,
                },
            )
        else:
            staged_change = self._pending.put(
                user.telegram_user_id,
                "book",
                {"doctor_id": str(doctor_id), "slot_start": check.slot.start.isoformat(), **when},
            )
        reply = summary(staged_change, patient)
        return reply if reply is not None else Reply(EXPIRED)
