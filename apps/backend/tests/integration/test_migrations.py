"""Every revision must downgrade cleanly and upgrade again (Global Constraint: reversible migrations)."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from clinic.config import Settings

from .conftest import run_alembic
from .test_schema import EXPECTED_TABLES


async def _tables(engine: AsyncEngine, schema: str) -> set[str]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("select table_name from information_schema.tables where table_schema = :schema"),
            {"schema": schema},
        )
        return set(rows.scalars().all()) - {"alembic_version"}


async def test_upgrade_downgrade_upgrade(
    settings: Settings, migrator_engine: AsyncEngine, test_engine: AsyncEngine
) -> None:
    schema = settings.db_test_schema
    try:
        run_alembic(settings, "downgrade", "base")
        await migrator_engine.dispose()
        assert await _tables(migrator_engine, schema) == set()

        run_alembic(settings, "upgrade", "head")
        assert await _tables(migrator_engine, schema) == EXPECTED_TABLES

        run_alembic(settings, "downgrade", "base")
        run_alembic(settings, "upgrade", "head")
        assert await _tables(migrator_engine, schema) == EXPECTED_TABLES
    finally:
        run_alembic(settings, "upgrade", "head")
        # Pooled connections cache statements for the dropped tables; start fresh.
        await migrator_engine.dispose()
        await test_engine.dispose()
