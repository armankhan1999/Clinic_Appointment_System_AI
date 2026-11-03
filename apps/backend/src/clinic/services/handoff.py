"""Hand a patient over to clinic staff (FR-15, E5-S4)."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from clinic.domain.results import ResultCode
from clinic.services.audit import AuditService
from clinic.services.tickets import TicketReason, TicketService


class HandoffService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def request(self, patient_id: UUID, reason: TicketReason) -> ResultCode:
        """Open a ticket, or confirm the open one (E5-S4-AC1, AC3). The reason is an enum, never free text."""
        async with self._session_factory() as session, session.begin():
            code, _ = await TicketService.open_or_get(session, patient_id=patient_id, reason=reason)
            AuditService.record(
                session,
                actor_type="agent",
                actor_id=None,
                action="handoff.request",
                args={"reason": reason},
                result=code,
                patient_id=patient_id,
                latency_ms=None,
            )
        return code
