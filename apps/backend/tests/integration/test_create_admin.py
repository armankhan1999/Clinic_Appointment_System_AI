"""IMP-04 bootstrap: the first admin account is created from the command line, password never echoed."""

from collections.abc import Callable

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from clinic.services.staff_auth import StaffAuthService
from create_admin import AdminBootstrapError, create_admin, read_password

from .api_harness import settings_secret

Factory = async_sessionmaker[AsyncSession]


def answers(*replies: str) -> Callable[[str], str]:
    queue = list(replies)
    return lambda _prompt: queue.pop(0)


async def test_creates_an_admin_who_can_sign_in(session_factory: Factory) -> None:
    await create_admin(session_factory, settings_secret(), "Owner", "Clinic Owner", "owner passphrase 1")
    result = await StaffAuthService(session_factory, secret=settings_secret()).login(
        "owner", "owner passphrase 1"
    )
    assert result.principal is not None
    assert result.principal.role == "admin"


async def test_refuses_an_existing_username_case_insensitively(session_factory: Factory) -> None:
    await create_admin(session_factory, settings_secret(), "owner", "Clinic Owner", "owner passphrase 1")
    with pytest.raises(AdminBootstrapError, match="already exists"):
        await create_admin(session_factory, settings_secret(), "OWNER", "Someone", "another passphrase")


async def test_refuses_a_weak_password_or_bad_username(session_factory: Factory) -> None:
    with pytest.raises(AdminBootstrapError, match="12"):
        await create_admin(session_factory, settings_secret(), "owner", "Clinic Owner", "short")
    with pytest.raises(AdminBootstrapError, match="usernames"):
        await create_admin(session_factory, settings_secret(), "no spaces allowed", "X", "owner passphrase 1")


def test_password_must_be_typed_the_same_twice() -> None:
    assert read_password(answers("owner passphrase 1", "owner passphrase 1")) == "owner passphrase 1"
    with pytest.raises(AdminBootstrapError, match="did not match"):
        read_password(answers("owner passphrase 1", "owner passphrase 2"))
