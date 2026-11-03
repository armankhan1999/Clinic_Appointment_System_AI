"""Approved clinic information (FR-14, E5-S1, IMP-02), read per question so admin edits apply at once."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from clinic.db.models import ClinicInfo


@dataclass(frozen=True)
class FaqEntry:
    topic: str
    answer: str


def _normalise(text: str) -> str:
    return " ".join(text.casefold().replace("_", " ").replace("-", " ").split())


class FaqService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def _entries(self) -> list[ClinicInfo]:
        async with self._session_factory() as session:
            return list((await session.scalars(select(ClinicInfo).order_by(ClinicInfo.topic))).all())

    async def find(self, topic: str) -> FaqEntry | None:
        """Exact topic or alias match only (E5-S1-AC1); no fuzzy guessing (E5-S1-AC2)."""
        wanted = _normalise(topic)
        for entry in await self._entries():
            names = {_normalise(entry.topic), *(_normalise(alias) for alias in entry.aliases)}
            if wanted in names:
                return FaqEntry(entry.topic, entry.answer)
        return None

    async def topics(self) -> list[str]:
        return [entry.topic for entry in await self._entries()]
