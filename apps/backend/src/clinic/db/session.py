"""Async engine and session factory for one DbTarget (role + schema)."""

import ssl
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from clinic.config import DbTarget, Settings

log = structlog.get_logger(__name__)


class InsecureDatabaseTlsError(RuntimeError):
    """Production must verify the database certificate (CA and hostname)."""


def database_ssl(settings: Settings) -> ssl.SSLContext | str | bool:
    """verify-full with the Supabase CA; unverified or disabled TLS is allowed only outside production."""
    if settings.db_ssl == "disable":
        if settings.env == "production":
            raise InsecureDatabaseTlsError("DB_SSL=disable is not allowed in production")
        return False
    if settings.db_ssl_root_cert is not None:
        context = ssl.create_default_context(cafile=str(settings.db_ssl_root_cert))
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        return context
    if settings.env == "production":
        raise InsecureDatabaseTlsError(
            "DB_SSL_ROOT_CERT must point to the Supabase CA certificate in production"
        )
    log.warning("db_tls_unverified", hint="set DB_SSL_ROOT_CERT to enable certificate verification")
    return "require"


def make_engine(target: DbTarget, settings: Settings, *, null_pool: bool = False) -> AsyncEngine:
    options: dict[str, Any] = {
        "pool_pre_ping": True,
        # SQL errors must never carry bound values such as phone numbers into logs.
        "hide_parameters": True,
        "connect_args": {
            "ssl": database_ssl(settings),
            "server_settings": {"application_name": f"clinic-{target.role}"},
        },
        "execution_options": {"schema_translate_map": {None: target.schema}},
    }
    if null_pool:
        options["poolclass"] = NullPool
    else:
        options.update(pool_size=5, max_overflow=5, pool_recycle=1800)
    return create_async_engine(target.url(settings), **options)


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
