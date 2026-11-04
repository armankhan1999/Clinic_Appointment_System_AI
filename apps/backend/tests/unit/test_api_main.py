"""`clinic-api` options: normal serving, and auto-reload for live development (never in production)."""

from pathlib import Path

import pytest

from clinic.api.__main__ import serve_options

from .test_config import make_settings


def test_normal_serving_binds_localhost_without_reload() -> None:
    options = serve_options(make_settings(api_port=8010), reload=False)
    assert (options["host"], options["port"], options["reload"]) == ("127.0.0.1", 8010, False)
    assert options["access_log"] is False, "the request middleware logs paths without query strings"


def test_reload_watches_only_the_backend_source() -> None:
    options = serve_options(make_settings(env="development"), reload=True)
    assert options["reload"] is True
    assert [Path(d).parts[-2:] for d in options["reload_dirs"]] == [("src", "clinic")]


def test_reload_is_refused_in_production() -> None:
    with pytest.raises(SystemExit, match="production"):
        serve_options(make_settings(env="production", db_ssl_root_cert=None), reload=True)
