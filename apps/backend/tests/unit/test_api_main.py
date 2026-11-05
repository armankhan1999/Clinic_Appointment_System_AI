"""`clinic-api` serving options."""

from clinic.api.__main__ import serve_options

from .test_config import make_settings


def test_serving_binds_localhost_on_the_configured_port() -> None:
    options = serve_options(make_settings(api_port=8010))
    assert (options["host"], options["port"], options["factory"]) == ("127.0.0.1", 8010, True)
    assert options["access_log"] is False, "the request middleware logs paths without query strings"
    assert "reload" not in options


def test_idle_connections_outlive_the_dashboard_proxy() -> None:
    # Node's global HTTP agent (the Next.js rewrite proxy) idles sockets for 5 s, as uvicorn did, so the
    # API could close a socket the proxy was reusing (ECONNRESET, then 500 "Failed to proxy").
    options = serve_options(make_settings(api_port=8010))
    assert options["timeout_keep_alive"] > 60, "longer than the proxy's 5 s and a typical 60 s load balancer"
