"""In-process staff API client for integration tests (real app, real test schema, real cookies)."""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import datetime

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from clinic.api.app import create_app
from clinic.config import Settings
from clinic.services.staff_auth import Role, StaffAuthService

PASSWORD = "front desk password"


def settings_secret() -> bytes:
    from clinic.config import get_settings

    return get_settings().auth_secret.get_secret_value().encode()


async def ready() -> bool:
    return True


@asynccontextmanager
async def api_client(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession], clock: Callable[[], datetime]
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(
        settings.model_copy(update={"env": "test"}),
        readiness=ready,
        session_factory=session_factory,
        clock=clock,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


async def add_staff(session_factory: async_sessionmaker[AsyncSession], username: str, role: Role) -> None:
    await StaffAuthService(session_factory, secret=settings_secret()).create_user(
        username=username, display_name=username.title(), role=role, password=PASSWORD, actor_id=None
    )


async def login(client: httpx.AsyncClient, username: str) -> dict[str, str]:
    """Log in and return the headers a write request needs (the CSRF token)."""
    response = await client.post("/api/v1/auth/login", json={"username": username, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": response.json()["csrf_token"]}
