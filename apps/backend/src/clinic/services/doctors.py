"""Doctor directory (E2-S1, IMP-01)."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from clinic.db.models import Doctor, DoctorSchedule


@dataclass(frozen=True)
class DoctorView:
    id: UUID
    name: str
    specialty: str
    working_weekdays: tuple[int, ...]  # 0 = Monday


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class DoctorService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def list_active(self, specialty: str | None = None) -> list[DoctorView]:
        """Active doctors only (E2-S1-AC2), optionally filtered by a case-insensitive specialty fragment."""
        weekdays = func.array_remove(func.array_agg(DoctorSchedule.weekday.distinct()), None)
        query = (
            select(Doctor.id, Doctor.name, Doctor.specialty, weekdays)
            .outerjoin(DoctorSchedule, DoctorSchedule.doctor_id == Doctor.id)
            .where(Doctor.active.is_(True))
            .group_by(Doctor.id)
            .order_by(Doctor.name)
        )
        if specialty and specialty.strip():
            pattern = f"%{_escape_like(specialty.strip())}%"
            query = query.where(Doctor.specialty.ilike(pattern, escape="\\"))
        async with self._session_factory() as session:
            rows = (await session.execute(query)).all()
        return [
            DoctorView(id=row[0], name=row[1], specialty=row[2], working_weekdays=tuple(sorted(row[3] or ())))
            for row in rows
        ]
