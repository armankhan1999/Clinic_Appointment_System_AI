"""Alembic environment: runs as clinic_migrator against one configured schema (D-17, D-20)."""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection, text

from clinic.config import DbTarget, get_settings
from clinic.db.models import Base
from clinic.db.session import make_engine

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
schema = context.get_x_argument(as_dictionary=True).get("schema", settings.db_schema)
target = DbTarget.migrator(settings, schema)  # rejects any schema other than the two configured ones
config.attributes["schema"] = schema
config.attributes["app_role"] = DbTarget.app_role_for_schema(settings, schema)


def _run(connection: Connection) -> None:
    # Session-level setting, committed before Alembic opens its own transaction.
    connection.execute(text(f'SET search_path TO "{schema}"'))
    connection.commit()
    context.configure(connection=connection, target_metadata=Base.metadata, version_table_schema=schema)
    with context.begin_transaction():
        context.run_migrations()


async def _run_async() -> None:
    engine = make_engine(target, settings, null_pool=True)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_run)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    raise SystemExit("Offline SQL generation is not supported; run against the database.")
asyncio.run(_run_async())
