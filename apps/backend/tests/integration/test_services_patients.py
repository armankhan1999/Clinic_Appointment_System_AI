"""Patient registration rules (E1-S2, E1-S3-AC3, IMP-14)."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from clinic.db.models import AuditLog, HandoffTicket, Patient
from clinic.services.patients import PatientService, PhoneCheck, RegistrationOutcome

from .factories import make_patient

Factory = async_sessionmaker[AsyncSession]
PHONE = "+12025550150"
CONSENT = datetime(2030, 1, 1, 9, 30, tzinfo=UTC)


async def test_new_patient_is_registered_with_consent(session_factory: Factory) -> None:
    service = PatientService(session_factory)
    assert await service.check_phone(PHONE, telegram_user_id=111) == PhoneCheck.AVAILABLE
    result = await service.register_from_telegram(
        telegram_user_id=111, phone=PHONE, full_name="Asha Rao", consented_at=CONSENT
    )
    assert result.outcome == RegistrationOutcome.REGISTERED
    assert result.patient is not None
    assert result.patient.first_name == "Asha"
    async with session_factory() as session:
        stored = await session.scalar(select(Patient))
        audit = await session.scalar(select(AuditLog))
    assert stored is not None
    assert (stored.telegram_user_id, stored.phone, stored.full_name) == (111, PHONE, "Asha Rao")
    assert (stored.consent_at, stored.consent_source, stored.registered_via) == (CONSENT, "telegram", "bot")
    assert audit is not None
    assert (audit.action, audit.actor_type, audit.result) == (
        "patient.register",
        "patient_button",
        "REGISTERED",
    )
    assert audit.args_json == {}
    assert audit.patient_id == stored.id


async def test_lookup_by_telegram_id(session_factory: Factory) -> None:
    service = PatientService(session_factory)
    assert await service.get_by_telegram(111) is None
    await service.register_from_telegram(
        telegram_user_id=111, phone=PHONE, full_name="Asha Rao", consented_at=CONSENT
    )
    found = await service.get_by_telegram(111)
    assert found is not None
    assert found.full_name == "Asha Rao"


async def test_walk_in_with_same_phone_is_linked_not_duplicated(session_factory: Factory) -> None:
    async with session_factory() as session:
        walk_in = await make_patient(session, phone=PHONE, name="A Rao")
        await session.commit()
    service = PatientService(session_factory)
    assert await service.check_phone(PHONE, telegram_user_id=111) == PhoneCheck.WALK_IN_MATCH
    result = await service.register_from_telegram(
        telegram_user_id=111, phone=PHONE, full_name="Asha Rao", consented_at=CONSENT
    )
    assert result.outcome == RegistrationOutcome.LINKED_WALK_IN
    async with session_factory() as session:
        patients = (await session.scalars(select(Patient))).all()
    assert len(patients) == 1
    assert patients[0].id == walk_in.id
    assert (patients[0].telegram_user_id, patients[0].full_name) == (111, "Asha Rao")
    assert (patients[0].consent_at, patients[0].consent_source) == (CONSENT, "telegram")


async def test_phone_linked_to_another_telegram_account_is_not_linked(session_factory: Factory) -> None:
    async with session_factory() as session:
        owner = await make_patient(session, phone=PHONE, telegram_user_id=999)
        await session.commit()
    service = PatientService(session_factory)
    assert await service.check_phone(PHONE, telegram_user_id=111) == PhoneCheck.LINKED_ELSEWHERE
    for _ in range(2):
        result = await service.register_from_telegram(
            telegram_user_id=111, phone=PHONE, full_name="Someone Else", consented_at=CONSENT
        )
        assert result.outcome == RegistrationOutcome.LINKED_ELSEWHERE
        assert result.patient is None
    async with session_factory() as session:
        patients = (await session.scalars(select(Patient))).all()
        tickets = (await session.scalars(select(HandoffTicket))).all()
    assert [p.telegram_user_id for p in patients] == [999]
    assert [(t.patient_id, t.reason, t.status) for t in tickets] == [
        (owner.id, "registration_conflict", "open")
    ]


async def test_same_telegram_user_registering_again_gets_existing_record(session_factory: Factory) -> None:
    service = PatientService(session_factory)
    await service.register_from_telegram(
        telegram_user_id=111, phone=PHONE, full_name="Asha Rao", consented_at=CONSENT
    )
    assert await service.check_phone(PHONE, telegram_user_id=111) == PhoneCheck.ALREADY_YOURS
    again = await service.register_from_telegram(
        telegram_user_id=111, phone=PHONE, full_name="Asha Rao", consented_at=CONSENT
    )
    assert again.outcome == RegistrationOutcome.ALREADY_REGISTERED
    async with session_factory() as session:
        assert len((await session.scalars(select(Patient))).all()) == 1


async def test_deleted_patient_is_treated_as_unknown(session_factory: Factory) -> None:
    async with session_factory() as session:
        patient = await make_patient(session, telegram_user_id=111, phone=PHONE)
        await session.commit()
    async with session_factory() as session:
        stored = await session.get_one(Patient, patient.id)
        stored.deleted_at = datetime.now(UTC)
        stored.phone = None
        stored.telegram_user_id = None
        stored.full_name = "Deleted patient"
        await session.commit()
    service = PatientService(session_factory)
    assert await service.get_by_telegram(111) is None
    assert await service.check_phone(PHONE, telegram_user_id=111) == PhoneCheck.AVAILABLE
    result = await service.register_from_telegram(
        telegram_user_id=111, phone=PHONE, full_name="Asha Rao", consented_at=CONSENT
    )
    assert result.outcome == RegistrationOutcome.REGISTERED
    assert result.patient is not None
    assert result.patient.id != patient.id, "a deleted record must never be reactivated"
