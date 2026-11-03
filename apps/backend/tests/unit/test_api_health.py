"""API conventions: health/readiness, request ids, error envelope, security headers (api-and-auth.md)."""

import re
from collections.abc import Awaitable, Callable

import httpx
import pytest
from fastapi import FastAPI

from clinic.api.app import create_app

from .test_config import make_settings


def client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")


async def ready() -> bool:
    return True


async def not_ready() -> bool:
    return False


async def broken() -> bool:
    raise ConnectionError("db down")


async def test_healthz_is_ok_and_echoes_a_well_formed_request_id() -> None:
    async with client(create_app(make_settings(), readiness=ready)) as c:
        response = await c.get("/healthz", headers={"X-Request-ID": "abc-12345678"})
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["X-Request-ID"] == "abc-12345678"


async def test_malformed_request_id_is_replaced() -> None:
    async with client(create_app(make_settings(), readiness=ready)) as c:
        response = await c.get("/healthz", headers={"X-Request-ID": "bad id <script>"})
    assert re.fullmatch(r"[0-9a-f]{32}", response.headers["X-Request-ID"])


@pytest.mark.parametrize(
    ("probe", "status", "body"), [(ready, 200, "ready"), (not_ready, 503, "unavailable")]
)
async def test_readyz_reflects_the_database(
    probe: Callable[[], Awaitable[bool]], status: int, body: str
) -> None:
    async with client(create_app(make_settings(), readiness=probe)) as c:
        response = await c.get("/readyz")
    assert (response.status_code, response.json()) == (status, {"status": body})


async def test_readyz_hides_probe_errors() -> None:
    async with client(create_app(make_settings(), readiness=broken)) as c:
        response = await c.get("/readyz")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
    assert "db down" not in response.text


async def test_unknown_route_uses_the_error_envelope() -> None:
    async with client(create_app(make_settings(), readiness=ready)) as c:
        response = await c.get("/api/v1/nope")
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "NOT_FOUND"
    assert error["request_id"] == response.headers["X-Request-ID"]
    assert set(error) == {"code", "message", "request_id"}


async def test_security_headers_are_set() -> None:
    async with client(create_app(make_settings(), readiness=ready)) as c:
        response = await c.get("/healthz")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert response.headers["Cache-Control"] == "no-store"


async def test_api_docs_only_in_development() -> None:
    async with client(create_app(make_settings(env="development"), readiness=ready)) as c:
        assert (await c.get("/api/v1/openapi.json")).status_code == 200
    async with client(
        create_app(make_settings(env="production", db_ssl_root_cert=None), readiness=ready)
    ) as c:
        assert (await c.get("/api/v1/openapi.json")).status_code == 404
        assert (await c.get("/api/v1/docs")).status_code == 404
