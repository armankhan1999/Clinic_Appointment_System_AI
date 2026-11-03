"""Database TLS policy: verify-full when a CA file is configured, never unverified in production."""

import ssl
from pathlib import Path

import pytest

from clinic.db.session import InsecureDatabaseTlsError, database_ssl

from .test_config import make_settings


@pytest.fixture
def ca_file(tmp_path: Path) -> Path:
    # A syntactically valid self-signed CA, generated once for tests (public, no private key).
    pem = Path(__file__).with_name("fixtures") / "test-ca.pem"
    target = tmp_path / "ca.pem"
    target.write_bytes(pem.read_bytes())
    return target


def test_configured_ca_gives_full_verification(ca_file: Path) -> None:
    context = database_ssl(make_settings(db_ssl_root_cert=ca_file))
    assert isinstance(context, ssl.SSLContext)
    assert context.check_hostname is True
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.minimum_version >= ssl.TLSVersion.TLSv1_2


def test_development_without_ca_falls_back_to_encrypted_unverified() -> None:
    assert database_ssl(make_settings(env="development")) == "require"


def test_production_without_ca_refuses_to_connect() -> None:
    with pytest.raises(InsecureDatabaseTlsError, match="DB_SSL_ROOT_CERT"):
        database_ssl(make_settings(env="production"))


def test_missing_ca_file_is_rejected_at_startup(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="db_ssl_root_cert"):
        make_settings(db_ssl_root_cert=tmp_path / "missing.crt")


def test_tls_can_be_disabled_for_a_local_ci_database() -> None:
    assert database_ssl(make_settings(env="test", db_ssl="disable")) is False


def test_disabling_tls_is_refused_in_production(ca_file: Path) -> None:
    with pytest.raises(InsecureDatabaseTlsError, match="DB_SSL=disable"):
        database_ssl(make_settings(env="production", db_ssl="disable", db_ssl_root_cert=ca_file))
