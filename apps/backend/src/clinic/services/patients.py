"""Patient identity and Telegram registration (E1-S2, E1-S3, IMP-14)."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from clinic.db.models import Appointment, Patient
from clinic.domain.patients import first_name
from clinic.services.audit import AuditService
from clinic.services.tickets import TicketService


@dataclass(frozen=True)
class PatientView:
    id: UUID
    full_name: str
    phone: str
    telegram_user_id: int | None

    @property
    def first_name(self) -> str:
        return first_name(self.full_name)


class PhoneCheck(StrEnum):
    AVAILABLE = "AVAILABLE"
    WALK_IN_MATCH = "WALK_IN_MATCH"
    LINKED_ELSEWHERE = "LINKED_ELSEWHERE"
    ALREADY_YOURS = "ALREADY_YOURS"


class RegistrationOutcome(StrEnum):
    REGISTERED = "REGISTERED"
    LINKED_WALK_IN = "LINKED_WALK_IN"
    LINKED_ELSEWHERE = "LINKED_ELSEWHERE"
    ALREADY_REGISTERED = "ALREADY_REGISTERED"


@dataclass(frozen=True)
class RegistrationResult:
    outcome: RegistrationOutcome
    patient: PatientView | None


def _view(patient: Patient) -> PatientView:
    if patient.full_name is None or patient.phone is None:
        raise ValueError("an active patient always has a name and phone (ck_patients_identity)")
    return PatientView(patient.id, patient.full_name, patient.phone, patient.telegram_user_id)


def _phone_check(owner: Patient | None, telegram_user_id: int) -> PhoneCheck:
    if owner is None:
        return PhoneCheck.AVAILABLE
    if owner.telegram_user_id is None:
        return PhoneCheck.WALK_IN_MATCH
    if owner.telegram_user_id == telegram_user_id:
        return PhoneCheck.ALREADY_YOURS
    return PhoneCheck.LINKED_ELSEWHERE


def _audit(session: AsyncSession, patient_id: UUID, outcome: RegistrationOutcome) -> None:
    AuditService.record(
        session,
        actor_type="patient_button",
        actor_id=None,
        action="patient.register",
        args={},
        result=outcome,
        patient_id=patient_id,
        latency_ms=None,
    )


class PatientService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get_by_telegram(self, telegram_user_id: int) -> PatientView | None:
        async with self._session_factory() as session:
            patient = await session.scalar(
                select(Patient).where(
                    Patient.telegram_user_id == telegram_user_id, Patient.deleted_at.is_(None)
                )
            )
        return _view(patient) if patient else None

    async def check_phone(self, phone: str, *, telegram_user_id: int) -> PhoneCheck:
        async with self._session_factory() as session:
            owner = await session.scalar(
                select(Patient).where(Patient.phone == phone, Patient.deleted_at.is_(None))
            )
        return _phone_check(owner, telegram_user_id)

    async def register_from_telegram(
        self, *, telegram_user_id: int, phone: str, full_name: str, consented_at: datetime
    ) -> RegistrationResult:
        """Create or link the patient in one transaction; nothing is stored before this call (E1-S3-AC2)."""
        try:
            return await self._register(telegram_user_id, phone, full_name, consented_at)
        except IntegrityError:
            # Lost a race on the phone or Telegram ID unique constraint; the retry sees the winner's row.
            return await self._register(telegram_user_id, phone, full_name, consented_at)

    async def _register(
        self, telegram_user_id: int, phone: str, full_name: str, consented_at: datetime
    ) -> RegistrationResult:
        async with self._session_factory() as session, session.begin():
            mine = await session.scalar(
                select(Patient).where(
                    Patient.telegram_user_id == telegram_user_id, Patient.deleted_at.is_(None)
                )
            )
            if mine is not None:
                return RegistrationResult(RegistrationOutcome.ALREADY_REGISTERED, _view(mine))
            owner = await session.scalar(
                select(Patient).where(Patient.phone == phone, Patient.deleted_at.is_(None)).with_for_update()
            )
            if owner is not None and _phone_check(owner, telegram_user_id) is PhoneCheck.LINKED_ELSEWHERE:
                await TicketService.open_or_get(session, patient_id=owner.id, reason="registration_conflict")
                _audit(session, owner.id, RegistrationOutcome.LINKED_ELSEWHERE)
                return RegistrationResult(RegistrationOutcome.LINKED_ELSEWHERE, None)
            if owner is not None:  # walk-in record created by staff with the same phone (IMP-14)
                owner.telegram_user_id = telegram_user_id
                owner.full_name = full_name
                owner.consent_at = consented_at
                owner.consent_source = "telegram"
                patient, outcome = owner, RegistrationOutcome.LINKED_WALK_IN
            else:
                patient = Patient(
                    telegram_user_id=telegram_user_id,
                    phone=phone,
                    full_name=full_name,
                    consent_at=consented_at,
                    consent_source="telegram",
                    registered_via="bot",
                )
                session.add(patient)
                outcome = RegistrationOutcome.REGISTERED
            await session.flush()
            _audit(session, patient.id, outcome)
            return RegistrationResult(outcome, _view(patient))

    async def flag_phone_conflict(self, phone: str) -> None:
        """E1-S2-AC4: the sender's own number belongs to another Telegram account; ask staff to follow up."""
        async with self._session_factory() as session, session.begin():
            owner = await session.scalar(
                select(Patient).where(Patient.phone == phone, Patient.deleted_at.is_(None))
            )
            if owner is None:
                return
            await TicketService.open_or_get(session, patient_id=owner.id, reason="registration_conflict")
            AuditService.record(
                session,
                actor_type="patient_button",
                actor_id=None,
                action="patient.phone_conflict",
                args={},
                result="LINKED_ELSEWHERE",
                patient_id=owner.id,
                latency_ms=None,
            )

    async def delete_patient(self, patient_id: UUID, *, now: datetime) -> int:
        """E1-S4-AC2: cancel upcoming appointments, anonymise, set deleted_at. Returns the cancelled count."""
        async with self._session_factory() as session, session.begin():
            patient = await session.scalar(
                select(Patient)
                .where(Patient.id == patient_id, Patient.deleted_at.is_(None))
                .with_for_update()
            )
            if patient is None:
                return 0
            upcoming = (
                await session.scalars(
                    select(Appointment)
                    .where(
                        Appointment.patient_id == patient_id,
                        Appointment.status == "booked",
                        Appointment.start_time > now,
                    )
                    .with_for_update()
                )
            ).all()
            for appointment in upcoming:
                appointment.status = "cancelled"
                appointment.cancelled_at = now
                appointment.cancelled_by_kind = "patient"
                appointment.cancel_reason = "Patient deleted their data"
            # GAP-25: Telegram ID cleared too, so the sender is treated as a new user (E1-S4-AC3).
            patient.full_name = "Deleted patient"
            patient.phone = None
            patient.telegram_user_id = None
            patient.deleted_at = now
            AuditService.record(
                session,
                actor_type="patient_button",
                actor_id=None,
                action="patient.delete",
                args={"cancelled_appointments": len(upcoming)},
                result="OK",
                patient_id=patient_id,
                latency_ms=None,
            )
            return len(upcoming)
