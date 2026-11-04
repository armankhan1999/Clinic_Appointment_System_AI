"""Drives ConversationService as a scripted patient against the real model and test schema (E7-S5).

Wiring mirrors clinic.runtime.build_bot_runtime (same prompt, tools, audit writer and time budget); only the
clock is pinned so seeded schedules give the same free slots on every run.
"""

import json
import time as perf
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from clinic.agent.grounding import extract_times
from clinic.agent.llm import LLM, LlmTurn, LlmUnavailableError, ToolResults, TranscriptItem
from clinic.agent.loop import AgentLoop, AuditEntry, db_audit_writer
from clinic.agent.memory import ConversationMemory
from clinic.agent.tools import AgentServices, ToolSpec, build_registry
from clinic.config import Settings
from clinic.conversation.service import ConversationService
from clinic.db.models import Appointment, Doctor, Patient
from clinic.domain.messages import IncomingUser, Reply
from clinic.services.alerts import AlertService
from clinic.services.availability import AvailabilityService
from clinic.services.booking import BookingService
from clinic.services.clinic_settings import ClinicSettingsService
from clinic.services.doctors import DoctorService
from clinic.services.faq import FaqService
from clinic.services.handoff import HandoffService
from clinic.services.patients import PatientService

from .eval_report import Turn

Factory = async_sessionmaker[AsyncSession]
NUDGE = "Yes, please go ahead."


@dataclass(frozen=True)
class Say:
    text: str


@dataclass(frozen=True)
class BookFirstOffered:
    """Ask for the earliest time the bot just offered, in the patient's own words."""

    template: str = "Please book {time}."
    optional: bool = False


@dataclass(frozen=True)
class Tap:
    """Tap a button on the latest reply; if it is missing, nudge once in words (unless optional)."""

    label: str = "Confirm"
    optional: bool = False


type Step = Say | BookFirstOffered | Tap


class CountingLLM:
    """Delegates to the real model; counts calls and keeps the cause of each failed call."""

    def __init__(self, inner: LLM) -> None:
        self._inner = inner
        self.calls = 0
        self.seconds = 0.0
        self.errors: list[str] = []
        self.evidence_times: set[int] = set()  # clock times in every tool result the model was shown

    async def generate(
        self, *, system: str, transcript: Sequence[TranscriptItem], tools: Sequence[ToolSpec[Any]]
    ) -> LlmTurn:
        self.calls += 1
        for item in transcript:
            if isinstance(item, ToolResults):
                for _, result in item.results:
                    self.evidence_times |= extract_times(json.dumps(result.payload(), default=str))
        started = perf.perf_counter()
        try:
            return await self._inner.generate(system=system, transcript=transcript, tools=tools)
        except LlmUnavailableError as exc:
            status = getattr(exc.__cause__, "code", None)
            self.errors.append(f"{exc}" + (f" (HTTP {status})" if status else ""))
            raise
        finally:
            self.seconds += perf.perf_counter() - started


def build_conversation(
    settings: Settings,
    session_factory: Factory,
    clock: Callable[[], datetime],
    llm: LLM,
    budget_seconds: float,
) -> tuple[ConversationService, list[AuditEntry]]:
    audit: list[AuditEntry] = []
    write = db_audit_writer(session_factory)

    async def record(entry: AuditEntry) -> None:
        audit.append(entry)
        await write(entry)

    agent = AgentLoop(
        llm,
        build_registry(),
        record,
        actor_id=settings.gemini_model,
        budget_seconds=budget_seconds,
    )
    clinic_settings = ClinicSettingsService(session_factory)
    services = AgentServices(
        doctors=DoctorService(session_factory),
        availability=AvailabilityService(session_factory, clinic_settings, clock=clock),
        booking=BookingService(session_factory, clinic_settings, clock=clock),
        alerts=AlertService(session_factory),
        faq=FaqService(session_factory),
        handoff=HandoffService(session_factory),
    )
    conversation = ConversationService(
        patients=PatientService(session_factory),
        settings=clinic_settings,
        agent=agent,
        memory=ConversationMemory(),
        services=services,
        clock=clock,
    )
    return conversation, audit


def _clock_label(minutes: int) -> str:
    hour, minute = divmod(minutes, 60)
    return f"{(hour - 1) % 12 + 1}:{minute:02d} {'AM' if hour < 12 else 'PM'}"


@dataclass
class ScriptedPatient:
    service: ConversationService
    user: IncomingUser
    llm: CountingLLM
    audit: list[AuditEntry]
    turns: list[Turn] = field(default_factory=list)
    last: list[Reply] = field(default_factory=list)
    shown: list[Reply] = field(default_factory=list)  # every reply so far, oldest first

    async def _turn(self, said: str, send: Callable[[], Any]) -> None:
        audit_mark, error_mark, model_mark = len(self.audit), len(self.llm.errors), self.llm.seconds
        started = perf.perf_counter()
        replies: list[Reply] = await send()
        seconds = perf.perf_counter() - started
        self.last = replies
        self.shown.extend(replies)
        self.turns.append(
            Turn(
                said=said,
                replies=[r.text for r in replies],
                buttons=[b.text for r in replies for row in r.inline_buttons for b in row],
                tools=[e.action for e in self.audit[audit_mark:]],
                seconds=round(seconds, 3),
                errors=tuple(self.llm.errors[error_mark:]),
                llm_seconds=round(self.llm.seconds - model_mark, 3),
                plain_replies=tuple(r.text for r in replies if not r.inline_buttons),
            )
        )

    async def say(self, text: str) -> None:
        await self._turn(text, lambda: self.service.handle_text(self.user, text))

    async def tap(self, label: str, data: str) -> None:
        await self._turn(f"[tap] {label}", lambda: self.service.handle_callback(self.user, data))

    def _button(self, label: str, replies: Sequence[Reply] | None = None) -> str | None:
        """The most recent button with this label, as a patient would tap the summary above."""
        for reply in reversed(self.shown if replies is None else replies):
            for row in reply.inline_buttons:
                for button in row:
                    if button.text == label and button.callback_data:
                        return button.callback_data
        return None

    async def run(self, steps: Sequence[Step]) -> list[str]:
        """Plays the script; returns why the script could not be followed (empty when it could)."""
        for step in steps:
            match step:
                case Say(text):
                    await self.say(text)
                case BookFirstOffered(template, optional):
                    if self._button("Confirm", self.last) is not None:
                        continue  # a summary is already on screen: the patient taps it (next step)
                    shown = " ".join(
                        [r.text for r in self.last]
                        + [b.text for r in self.last for row in r.inline_buttons for b in row]
                    )
                    offered = extract_times(shown)
                    if not offered:
                        if optional:
                            continue
                        return ["the bot offered no times to choose from"]
                    await self.say(template.format(time=_clock_label(min(offered))))
                case Tap(label, optional):
                    data = self._button(label)
                    if data is None and not optional:
                        await self.say(NUDGE)
                        data = self._button(label)
                    if data is None:
                        if optional:
                            continue
                        return [f"no '{label}' button was shown"]
                    await self.tap(label, data)
        return []


@dataclass(frozen=True)
class World:
    """What a check can see once the conversation is over."""

    patient_id: UUID
    tz: ZoneInfo
    before: dict[UUID, str]  # the patient's appointments before the conversation: id -> status
    mine: list[Appointment]  # the patient's appointments afterwards
    doctor_names: dict[UUID, str]
    foreign_refs: frozenset[str]
    foreign_names: frozenset[str]
    foreign_phones: frozenset[str]
    llm_calls: int
    turns: list[Turn]
    evidence_times: frozenset[int] = frozenset()  # minutes after midnight seen in tool results

    @property
    def said(self) -> str:
        return " ".join(t.said for t in self.turns)

    @property
    def replies(self) -> str:
        return " ".join(reply for t in self.turns for reply in t.replies)

    @property
    def tools(self) -> list[str]:
        return [tool for t in self.turns for tool in t.tools]

    def new_appointments(self) -> list[Appointment]:
        return [a for a in self.mine if a.id not in self.before]

    def local_day(self, appointment: Appointment) -> date:
        return appointment.start_time.astimezone(self.tz).date()

    def local_minutes(self, appointment: Appointment) -> int:
        local = appointment.start_time.astimezone(self.tz)
        return local.hour * 60 + local.minute


async def patient_appointments(session_factory: Factory, patient_id: UUID) -> list[Appointment]:
    async with session_factory() as session:
        return list(
            (
                await session.scalars(
                    select(Appointment)
                    .where(Appointment.patient_id == patient_id)
                    .order_by(Appointment.start_time)
                )
            ).all()
        )


async def snapshot(
    session_factory: Factory,
    patient_id: UUID,
    tz: ZoneInfo,
    before: dict[UUID, str],
    llm_calls: int,
    turns: list[Turn],
    evidence_times: frozenset[int] = frozenset(),
) -> World:
    async with session_factory() as session:
        doctors = {d.id: d.name for d in (await session.scalars(select(Doctor))).all()}
        others = (await session.scalars(select(Patient).where(Patient.id != patient_id))).all()
        foreign_refs = (
            await session.scalars(select(Appointment.ref).where(Appointment.patient_id != patient_id))
        ).all()
    return World(
        patient_id=patient_id,
        tz=tz,
        before=before,
        mine=await patient_appointments(session_factory, patient_id),
        doctor_names=doctors,
        foreign_refs=frozenset(foreign_refs),
        foreign_names=frozenset(name for p in others if (name := p.full_name)),
        foreign_phones=frozenset(phone for p in others if (phone := p.phone)),
        llm_calls=llm_calls,
        turns=turns,
        evidence_times=evidence_times,
    )
