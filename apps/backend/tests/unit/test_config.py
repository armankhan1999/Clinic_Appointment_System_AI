from typing import Any

import pytest
from pydantic import ValidationError

from clinic.config import DbTarget, Settings

SECRET_TOKEN = "123456:secret-telegram-token-value"
SECRET_KEY = "gemini-secret-key-value"


def make_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "env": "test",
        "supabase_project_ref": "abcdefghijklmnopqrst",
        "db_host": "aws-1-eu-west-3.pooler.supabase.com",
        "db_migrator_password": "migrator-password-value",
        "db_app_password": "app-password-value",
        "db_test_app_password": "test-app-password-value",
        "telegram_bot_token": SECRET_TOKEN,
        "gemini_api_key": SECRET_KEY,
        "gemini_model": "gemini-3.5-flash-lite",
        "clinic_timezone": "Asia/Kolkata",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_secrets_are_hidden_in_repr_and_str() -> None:
    settings = make_settings()
    rendered = repr(settings) + str(settings) + str(settings.gemini_api_key)
    for secret in (SECRET_TOKEN, SECRET_KEY, "app-password-value", "migrator-password-value"):
        assert secret not in rendered
    assert settings.telegram_bot_token.get_secret_value() == SECRET_TOKEN


def test_missing_required_secret_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    values: dict[str, Any] = {
        "env": "test",
        "supabase_project_ref": "abcdefghijklmnopqrst",
        "db_host": "h",
        "db_migrator_password": "x",
        "db_app_password": "x",
        "db_test_app_password": "x",
        "gemini_api_key": "x",
        "gemini_model": "m",
        "clinic_timezone": "Asia/Kolkata",
    }
    with pytest.raises(ValidationError, match="telegram_bot_token"):
        Settings(_env_file=None, **values)


def test_unknown_timezone_is_rejected() -> None:
    with pytest.raises(ValidationError, match="clinic_timezone"):
        make_settings(clinic_timezone="Mars/Olympus")


def test_valid_timezone_is_accepted() -> None:
    assert make_settings(clinic_timezone="Europe/Paris").clinic_timezone == "Europe/Paris"


def test_defaults() -> None:
    settings = make_settings()
    assert settings.db_port == 5432
    assert settings.db_name == "postgres"
    assert settings.db_schema == "clinic"
    assert settings.db_test_schema == "clinic_test"
    assert settings.llm_timeout_seconds == 8.0


def test_owner_password_key_is_never_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DB_OWNER_PASSWORD", "owner-secret")
    settings = make_settings()
    assert "owner-secret" not in repr(settings.model_dump())


def test_app_target_url_uses_pooler_role_naming() -> None:
    settings = make_settings()
    target = DbTarget.app(settings)
    url = target.url(settings)
    assert target.role == "clinic_app"
    assert target.schema == "clinic"
    assert url.drivername == "postgresql+asyncpg"
    assert url.username == "clinic_app.abcdefghijklmnopqrst"
    assert url.host == "aws-1-eu-west-3.pooler.supabase.com"
    assert url.port == 5432
    assert url.database == "postgres"
    assert "app-password-value" not in url.render_as_string(hide_password=True)
    assert url.password == "app-password-value"


def test_test_target_uses_test_role_and_schema() -> None:
    settings = make_settings()
    target = DbTarget.test(settings)
    assert (target.role, target.schema) == ("clinic_test_app", "clinic_test")
    assert target.url(settings).password == "test-app-password-value"


def test_migrator_target_accepts_only_configured_schemas() -> None:
    settings = make_settings()
    assert DbTarget.migrator(settings, "clinic_test").schema == "clinic_test"
    assert DbTarget.migrator(settings, "clinic").role == "clinic_migrator"
    with pytest.raises(ValueError, match="public"):
        DbTarget.migrator(settings, "public")


def test_app_role_for_schema() -> None:
    settings = make_settings()
    assert DbTarget.app_role_for_schema(settings, "clinic") == "clinic_app"
    assert DbTarget.app_role_for_schema(settings, "clinic_test") == "clinic_test_app"
    with pytest.raises(ValueError, match="other"):
        DbTarget.app_role_for_schema(settings, "other")


def test_api_port_defaults_to_8000_and_is_validated() -> None:
    assert make_settings().api_port == 8000
    assert make_settings(api_port=8010).api_port == 8010
    with pytest.raises(ValidationError, match="api_port"):
        make_settings(api_port=80)
