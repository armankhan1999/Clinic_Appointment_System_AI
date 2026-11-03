"""Application settings loaded from the environment (and the repository-root .env file)."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, FilePath, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

REPO_ROOT_ENV = Path(__file__).resolve().parents[4] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT_ENV, env_file_encoding="utf-8", extra="ignore")

    env: Literal["development", "test", "production"] = "development"

    # Supabase pooler logins are `role.<project_ref>`; leave empty for a plain Postgres server (CI).
    supabase_project_ref: str = ""
    db_host: str
    db_port: int = 5432
    db_name: str = "postgres"
    db_migrator_password: SecretStr
    db_app_password: SecretStr
    db_test_app_password: SecretStr
    db_schema: str = "clinic"
    db_test_schema: str = "clinic_test"
    # Supabase CA (prod-ca-2021.crt from Database Settings > SSL Configuration). Enables verify-full.
    db_ssl_root_cert: FilePath | None = None
    # "disable" exists only for the throwaway CI container; production refuses it.
    db_ssl: Literal["auto", "disable"] = "auto"

    telegram_bot_token: SecretStr
    gemini_api_key: SecretStr
    gemini_model: str
    llm_timeout_seconds: float = 8.0

    clinic_timezone: str
    log_level: str = "INFO"

    # The staff API binds to 127.0.0.1 only; the dashboard reaches it through a same-origin rewrite.
    api_port: int = Field(default=8000, ge=1024, le=65535)

    @model_validator(mode="after")
    def _separate_test_schema(self) -> Settings:
        # Test fixtures truncate the test schema; sharing it with the dev schema would wipe real data.
        if self.db_schema == self.db_test_schema:
            raise ValueError("DB_TEST_SCHEMA must differ from DB_SCHEMA")
        return self

    @field_validator("clinic_timezone")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown IANA time zone: {value!r}") from exc
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


@dataclass(frozen=True)
class DbTarget:
    """A database login role plus the schema it works in (D-17, D-20)."""

    role: str
    schema: str
    password: SecretStr

    @classmethod
    def app(cls, settings: Settings) -> DbTarget:
        return cls("clinic_app", settings.db_schema, settings.db_app_password)

    @classmethod
    def test(cls, settings: Settings) -> DbTarget:
        return cls("clinic_test_app", settings.db_test_schema, settings.db_test_app_password)

    @classmethod
    def migrator(cls, settings: Settings, schema: str) -> DbTarget:
        cls.app_role_for_schema(settings, schema)
        return cls("clinic_migrator", schema, settings.db_migrator_password)

    @staticmethod
    def app_role_for_schema(settings: Settings, schema: str) -> str:
        roles = {settings.db_schema: "clinic_app", settings.db_test_schema: "clinic_test_app"}
        if schema not in roles:
            raise ValueError(f"schema {schema!r} is not one of the configured schemas {sorted(roles)}")
        return roles[schema]

    def url(self, settings: Settings) -> URL:
        return URL.create(
            drivername="postgresql+asyncpg",
            username=f"{self.role}.{settings.supabase_project_ref}"
            if settings.supabase_project_ref
            else self.role,
            password=self.password.get_secret_value(),
            host=settings.db_host,
            port=settings.db_port,
            database=settings.db_name,
        )
