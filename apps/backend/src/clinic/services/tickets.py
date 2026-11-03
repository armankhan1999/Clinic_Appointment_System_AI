"""Handoff tickets for staff follow-up (E5-S4, DM-07)."""

from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from clinic.db.models import HandoffTicket
from clinic.domain.results import ResultCode

type TicketReason = Literal[
    "patient_requested", "agent_failed", "registration_conflict", "change_within_cutoff", "other"
]


async def _open_ticket_id(session: AsyncSession, patient_id: UUID) -> UUID | None:
    return await session.scalar(
        select(HandoffTicket.id).where(HandoffTicket.patient_id == patient_id, HandoffTicket.status == "open")
    )


class TicketService:
    @staticmethod
    async def open_or_get(
        session: AsyncSession, *, patient_id: UUID, reason: TicketReason
    ) -> tuple[ResultCode, UUID]:
        """Open a ticket in the caller's transaction, or return the patient's open one (E5-S4-AC3)."""
        existing = await _open_ticket_id(session, patient_id)
        if existing is not None:
            return ResultCode.ALREADY_OPEN, existing
        ticket = HandoffTicket(patient_id=patient_id, reason=reason)
        try:
            async with session.begin_nested():
                session.add(ticket)
        except IntegrityError:
            # A concurrent request opened one first; the partial unique index allows only one open ticket.
            concurrent = await _open_ticket_id(session, patient_id)
            if concurrent is None:
                raise
            return ResultCode.ALREADY_OPEN, concurrent
        return ResultCode.CREATED, ticket.id
