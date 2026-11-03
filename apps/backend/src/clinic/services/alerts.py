"""Emergency alerts for the staff dashboard (E5-S3-AC3, IMP-06). No message text is ever stored."""

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from clinic.db.models import EmergencyAlert
from clinic.services.audit import AuditService

DEDUPLICATION_WINDOW = timedelta(minutes=10)


class AlertService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def raise_emergency(self, *, patient_id: UUID | None, telegram_user_id: int, now: datetime) -> bool:
        """Record one alert per sender per 10 minutes. Returns True when a new alert was created."""
        async with self._session_factory() as session, session.begin():
            sender = [EmergencyAlert.telegram_user_id == telegram_user_id]
            if patient_id is not None:
                sender.append(EmergencyAlert.patient_id == patient_id)
            recent = await session.scalar(
                select(EmergencyAlert.id)
                .where(or_(*sender), EmergencyAlert.created_at > now - DEDUPLICATION_WINDOW)
                .limit(1)
            )
            if recent is not None:
                return False
            session.add(
                EmergencyAlert(patient_id=patient_id, telegram_user_id=telegram_user_id, created_at=now)
            )
            AuditService.record(
                session,
                actor_type="system",
                actor_id=None,
                action="emergency.alert",
                args={},
                result="CREATED",
                patient_id=patient_id,
                latency_ms=None,
            )
            return True
