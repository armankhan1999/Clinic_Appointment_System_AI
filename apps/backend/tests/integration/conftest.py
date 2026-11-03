"""Integration fixtures (D-17): schema `clinic_test`, role `clinic_test_app`; cleanup as `clinic_migrator`."""

import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from clinic.config import DbTarget, Settings, get_settings
from clinic.db.models import Base
from clinic.db.session import make_engine, make_session_factory

BACKEND_DIR = Path(__file__).resolve().parents[2]


def run_alembic(settings: Settings, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603  # fixed argv, no shell
        [sys.executable, "-m", "alembic", "-x", f"schema={settings.db_test_schema}", *args],
        cwd=BACKEND_DIR,
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture(scope="session")
def settings() -> Settings:
    return get_settings()


@pytest.fixture(scope="session")
def migrated(settings: Settings) -> None:
    run_alembic(settings, "upgrade", "head")


@pytest.fixture(scope="session")
async def test_engine(settings: Settings, migrated: None) -> AsyncIterator[AsyncEngine]:
    engine = make_engine(DbTarget.test(settings), settings)
    yield engine
    await engine.dispose()


@pytest.fixture(scope="session")
async def migrator_engine(settings: Settings, migrated: None) -> AsyncIterator[AsyncEngine]:
    engine = make_engine(DbTarget.migrator(settings, settings.db_test_schema), settings)
    yield engine
    await engine.dispose()


@pytest.fixture
async def clean_db(settings: Settings, migrator_engine: AsyncEngine) -> None:
    schema = settings.db_test_schema
    tables = ", ".join(f'"{schema}"."{table.name}"' for table in Base.metadata.sorted_tables)
    async with migrator_engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))
        await conn.execute(text(f'ALTER SEQUENCE "{schema}".appointment_ref_seq RESTART WITH 1'))


@pytest.fixture
def session_factory(test_engine: AsyncEngine, clean_db: None) -> async_sessionmaker[AsyncSession]:
    return make_session_factory(test_engine)
