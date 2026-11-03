"""Async engine and session factory for one DbTarget (role + schema)."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from clinic.config import DbTarget, Settings


def make_engine(target: DbTarget, settings: Settings, *, null_pool: bool = False) -> AsyncEngine:
    options: dict[str, Any] = {
        "pool_pre_ping": True,
        # TLS to the Supabase pooler. Certificate verification needs the project CA (risk R-DB-TLS).
        "connect_args": {"ssl": "require", "server_settings": {"application_name": f"clinic-{target.role}"}},
        "execution_options": {"schema_translate_map": {None: target.schema}},
    }
    if null_pool:
        options["poolclass"] = NullPool
    else:
        options.update(pool_size=5, max_overflow=5, pool_recycle=1800)
    return create_async_engine(target.url(settings), **options)


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
