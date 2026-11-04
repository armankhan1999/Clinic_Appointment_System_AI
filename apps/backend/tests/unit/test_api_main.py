"""`clinic-api` serving options."""

from clinic.api.__main__ import serve_options

from .test_config import make_settings


def test_serving_binds_localhost_on_the_configured_port() -> None:
    options = serve_options(make_settings(api_port=8010))
    assert (options["host"], options["port"], options["factory"]) == ("127.0.0.1", 8010, True)
    assert options["access_log"] is False, "the request middleware logs paths without query strings"
    assert "reload" not in options
