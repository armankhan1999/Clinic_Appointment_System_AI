"""Append-only audit trail of agent tool calls and data changes (FR-10, E7-S2)."""

from collections.abc import Mapping
from typing import Any, Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from clinic.db.models import AuditLog
from clinic.observability import request_id_var

type ActorType = Literal["agent", "staff", "system", "patient_button"]

# E7-S2-AC2 and NFR-06: the audit log never holds chat text or personal details.
FORBIDDEN_KEYS = frozenset({"text", "message", "name", "phone", "full_name"})


class ForbiddenAuditFieldError(ValueError):
    """An audit payload contained a field that could carry chat text or personal data."""


def _check_keys(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if key in FORBIDDEN_KEYS:
                raise ForbiddenAuditFieldError(f"audit args must not contain {key!r}")
            _check_keys(nested)
    elif isinstance(value, list | tuple):
        for item in value:
            _check_keys(item)


class AuditService:
    @staticmethod
    def record(
        session: AsyncSession,
        *,
        actor_type: ActorType,
        actor_id: str | None,
        action: str,
        args: Mapping[str, Any],
        result: str,
        patient_id: UUID | None,
        latency_ms: int | None,
        request_id: str | None = None,
    ) -> None:
        """Add an audit row to the caller's transaction, so it commits or rolls back with the change."""
        _check_keys(args)
        session.add(
            AuditLog(
                actor_type=actor_type,
                actor_id=actor_id,
                action=action,
                args_json=dict(args),
                result=str(result),
                patient_id=patient_id,
                latency_ms=latency_ms,
                request_id=request_id or request_id_var.get(),
            )
        )
