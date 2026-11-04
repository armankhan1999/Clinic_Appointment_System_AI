"""A synthetic patient with one of each item the Today attention panel shows (E6-S2-AC3).

    uv run python -m tests.e2e_support.attention_fixture

These come from the patient side, never from the staff API, so they are created here: an open handoff
ticket (through HandoffService, as the assistant opens it, E5-S4), an unacknowledged emergency alert
(E5-S3-AC3; patient only, no Telegram ID) and a booked appointment three days ahead flagged
staff_attention_reason="notification_failed" (as NotificationService flags it after failed retries,
E4-S4-AC2). Prints {"patient": {...}, "doctor": {...}, "ticket_id", "alert_id", "appointment": {...}}.
"""

import sys
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from clinic.db.models import EmergencyAlert, HandoffTicket
from clinic.services.clinic_settings import ClinicSettingsService
from clinic.services.handoff import HandoffService
from tests.e2e_support.common import (
    FixtureError,
    active_doctor,
    add_appointments,
    booked_ranges,
    describe_appointment,
    describe_doctor,
    describe_patient,
    first_free_start,
    new_patient,
    run,
)

LENGTH = timedelta(minutes=15)


async def create(session_factory: async_sessionmaker[AsyncSession]) -> dict[str, Any]:
    tz = (await ClinicSettingsService(session_factory).get()).tz
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    async with session_factory() as session, session.begin():
        patient = await new_patient(session, "Attention", now)
        doctor = await active_doctor(session, None)
        wanted = now + timedelta(days=3)
        start = first_free_start(wanted, LENGTH, await booked_ranges(session, doctor.id, wanted), LENGTH)
        [flagged] = await add_appointments(
            session, doctor=doctor, patient=patient, starts=[start], length=LENGTH, attention_at=now
        )
        alert = EmergencyAlert(patient_id=patient.id, created_at=now)
        session.add(alert)
        await session.flush()
        result: dict[str, Any] = {
            "patient": describe_patient(patient),
            "doctor": describe_doctor(doctor),
            "alert_id": alert.id,
            "appointment": describe_appointment(flagged, tz),
        }

    await HandoffService(session_factory).request(patient.id, "patient_requested")
    async with session_factory() as session:
        ticket_id = await session.scalar(
            select(HandoffTicket.id).where(
                HandoffTicket.patient_id == patient.id, HandoffTicket.status == "open"
            )
        )
    if ticket_id is None:
        raise FixtureError("the handoff ticket was not opened")
    result["ticket_id"] = ticket_id
    return result


if __name__ == "__main__":
    sys.exit(run(create))
