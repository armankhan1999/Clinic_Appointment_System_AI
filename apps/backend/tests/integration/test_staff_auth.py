"""Staff authentication (E6-S1-AC2/AC3, NFR-04, GAP-23): argon2id, lockout, server-side sessions."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from clinic.db.models import AuditLog, StaffSession, StaffUser
from clinic.domain.results import ResultCode
from clinic.services.staff_auth import Role, StaffAuthService, WeakPasswordError, csrf_token_for

Factory = async_sessionmaker[AsyncSession]
PASSWORD = "correct horse battery"


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2030, 1, 7, 9, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


async def _service(session_factory: Factory, clock: Clock, role: Role = "receptionist") -> StaffAuthService:
    service = StaffAuthService(session_factory, clock=clock)
    await service.create_user(
        username="Riya", display_name="Riya S", role=role, password=PASSWORD, actor_id=None
    )
    return service


async def test_passwords_are_stored_as_argon2id_hashes(session_factory: Factory) -> None:
    await _service(session_factory, Clock())
    async with session_factory() as session:
        user = await session.scalar(select(StaffUser))
    assert user is not None
    assert user.password_hash.startswith("$argon2id$")
    assert PASSWORD not in user.password_hash


async def test_short_passwords_are_refused(session_factory: Factory) -> None:
    with pytest.raises(WeakPasswordError):
        await StaffAuthService(session_factory).create_user(
            username="sam", display_name="Sam", role="admin", password="short", actor_id=None
        )


async def test_login_is_case_insensitive_on_username_and_creates_a_session(session_factory: Factory) -> None:
    service = await _service(session_factory, Clock())
    result = await service.login("riya", PASSWORD)
    assert result.code == ResultCode.OK
    assert result.principal is not None
    assert result.principal.role == "receptionist"
    assert result.session_token is not None
    async with session_factory() as session:
        stored = await session.scalar(select(StaffSession))
        audit = await session.scalar(select(AuditLog).where(AuditLog.action == "staff.login"))
    assert stored is not None
    assert result.session_token.encode() not in stored.token_hash, "only a hash of the token is stored"
    assert audit is not None
    assert (audit.actor_type, audit.result) == ("staff", "OK")


async def test_wrong_password_and_unknown_user_look_the_same(session_factory: Factory) -> None:
    service = await _service(session_factory, Clock())
    wrong = await service.login("riya", "not the password")
    unknown = await service.login("nobody", "not the password")
    assert (wrong.code, unknown.code) == (ResultCode.UNAUTHENTICATED, ResultCode.UNAUTHENTICATED)
    assert wrong.session_token is None


async def test_five_failures_in_fifteen_minutes_lock_the_account_for_fifteen_minutes(
    session_factory: Factory,
) -> None:
    clock = Clock()
    service = await _service(session_factory, clock)
    for _ in range(5):
        clock.now += timedelta(minutes=2)
        assert (await service.login("riya", "wrong")).code == ResultCode.UNAUTHENTICATED
    sixth = await service.login("riya", PASSWORD)
    assert sixth.code == ResultCode.ACCOUNT_LOCKED, (
        "E6-S1-AC3: the 6th try is refused even with the right password"
    )
    assert sixth.locked_until == clock.now + timedelta(minutes=15)
    clock.now += timedelta(minutes=16)
    assert (await service.login("riya", PASSWORD)).code == ResultCode.OK


async def test_failures_spread_over_more_than_fifteen_minutes_do_not_lock(session_factory: Factory) -> None:
    clock = Clock()
    service = await _service(session_factory, clock)
    for _ in range(5):
        clock.now += timedelta(minutes=4)
        await service.login("riya", "wrong")
    assert (await service.login("riya", PASSWORD)).code == ResultCode.OK


async def test_sessions_expire_on_idle_absolute_time_logout_and_deactivation(
    session_factory: Factory,
) -> None:
    clock = Clock()
    service = await _service(session_factory, clock)
    token = (await service.login("riya", PASSWORD)).session_token
    assert token is not None
    clock.now += timedelta(minutes=59)
    assert await service.authenticate(token) is not None
    clock.now += timedelta(minutes=61)
    assert await service.authenticate(token) is None, "60-minute idle timeout"

    token = (await service.login("riya", PASSWORD)).session_token
    assert token is not None
    for _ in range(14):  # 14 x 55 min = 770 min > 12 h, each step within the idle limit
        clock.now += timedelta(minutes=55)
        principal = await service.authenticate(token)
    assert principal is None, "12-hour absolute limit"

    token = (await service.login("riya", PASSWORD)).session_token
    assert token is not None
    principal = await service.authenticate(token)
    assert principal is not None
    await service.logout(principal.session_id)
    assert await service.authenticate(token) is None

    token = (await service.login("riya", PASSWORD)).session_token
    assert token is not None
    async with session_factory() as session:
        user = await session.scalar(select(StaffUser))
        assert user is not None
        user.active = False
        await session.commit()
    assert await service.authenticate(token) is None


def test_csrf_token_is_bound_to_the_session_token() -> None:
    assert csrf_token_for("a" * 43) == csrf_token_for("a" * 43)
    assert csrf_token_for("a" * 43) != csrf_token_for("b" * 43)
    assert len(csrf_token_for("a" * 43)) == 64
