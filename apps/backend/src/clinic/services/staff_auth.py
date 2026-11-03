"""Staff accounts and sessions (FR-09, E6-S1, NFR-04, D-08).

- Passwords are argon2id hashes; hashing runs in a worker thread so the event loop never blocks.
- Unknown usernames are verified against a dummy hash, so timing and messages do not reveal accounts.
- 5 failures within 15 minutes lock the account for 15 minutes (E6-S1-AC3, GAP-23). Unknown usernames
  get the same lockout, stored in the database like real accounts' (keyed by a hash of the name), and
  every path does the same hashing work, so neither the 423 nor the timing reveals an account.
- Sessions are opaque random tokens; only their SHA-256 is stored. 12 h absolute, 60 min idle.
- The CSRF token is an HMAC of the session token, so it is bound to the session and needs no storage.
"""

import asyncio
import hashlib
import hmac
import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from clinic.db.models import LoginFailure, StaffSession, StaffUser
from clinic.domain.results import ResultCode
from clinic.services.audit import AuditService
from clinic.services.availability import utc_now

type Role = Literal["receptionist", "admin"]

SESSION_ABSOLUTE = timedelta(hours=12)
SESSION_IDLE = timedelta(minutes=60)
SEEN_WRITE_INTERVAL = timedelta(minutes=1)  # throttles last_seen_at writes
LOCK_AFTER_FAILURES = 5
FAILURE_WINDOW = timedelta(minutes=15)
LOCK_DURATION = timedelta(minutes=15)
MIN_PASSWORD_LENGTH = 12
USERNAME_PATTERN = re.compile(r"^[a-z0-9._-]{3,40}$")
MAX_USERNAME_LENGTH = 80
FAILURE_RETENTION = timedelta(days=1)  # unknown-username rows older than this are purged

_hasher = PasswordHasher()  # argon2id with the library's current recommended parameters
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


class WeakPasswordError(ValueError):
    """The password is shorter than MIN_PASSWORD_LENGTH."""


class InvalidUsernameError(ValueError):
    """Usernames are 3-40 characters: lower-case letters, digits, dot, underscore, hyphen."""


@dataclass
class _Failures:
    count: int = 0
    first_at: datetime | None = None
    locked_until: datetime | None = None


def _register_failure(state: _Failures, now: datetime) -> None:
    if state.first_at is None or now - state.first_at > FAILURE_WINDOW:
        state.first_at, state.count = now, 1
    else:
        state.count += 1
    if state.count >= LOCK_AFTER_FAILURES:
        state.locked_until = now + LOCK_DURATION
        state.count, state.first_at = 0, None


@dataclass(frozen=True)
class StaffPrincipal:
    user_id: UUID
    username: str
    display_name: str
    role: Role
    session_id: UUID


@dataclass(frozen=True)
class LoginResult:
    code: ResultCode
    principal: StaffPrincipal | None = None
    session_token: str | None = None
    locked_until: datetime | None = None


def token_hash(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


def csrf_token_for(session_token: str) -> str:
    return hmac.new(session_token.encode(), b"clinic-csrf-v1", hashlib.sha256).hexdigest()


def csrf_matches(session_token: str, presented: str | None) -> bool:
    return presented is not None and hmac.compare_digest(csrf_token_for(session_token), presented)


async def hash_password(password: str) -> str:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise WeakPasswordError(f"passwords need at least {MIN_PASSWORD_LENGTH} characters")
    return await asyncio.to_thread(_hasher.hash, password)


async def _verify(password_hash: str, password: str) -> bool:
    try:
        return await asyncio.to_thread(_hasher.verify, password_hash, password)
    except VerifyMismatchError, VerificationError, InvalidHashError:
        return False


def normalise_username(username: str) -> str:
    value = username.strip().lower()
    if not USERNAME_PATTERN.fullmatch(value):
        raise InvalidUsernameError("usernames are 3-40 characters: a-z, 0-9, dot, underscore, hyphen")
    return value


def _principal(user: StaffUser, session_id: UUID) -> StaffPrincipal:
    role: Role = "admin" if user.role == "admin" else "receptionist"
    return StaffPrincipal(user.id, user.username, user.display_name, role, session_id)


class StaffAuthService:
    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], *, clock: Callable[[], datetime] = utc_now
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock

    async def create_user(
        self, *, username: str, display_name: str, role: Role, password: str, actor_id: UUID | None
    ) -> StaffUser:
        user = StaffUser(
            username=normalise_username(username),
            display_name=display_name.strip()[:80],
            role=role,
            password_hash=await hash_password(password),
        )
        async with self._session_factory() as session, session.begin():
            session.add(user)
            await session.flush()
            self._audit(session, actor_id, "staff_user.create", {"user_id": str(user.id), "role": role}, "OK")
        return user

    async def login(self, username: str, password: str) -> LoginResult:
        now = self._clock()
        async with self._session_factory() as session, session.begin():
            user = await session.scalar(
                select(StaffUser)
                .where(func.lower(StaffUser.username) == username.strip().lower())
                .with_for_update()
            )
            if user is None or not user.active:
                return await self._unknown_login(session, username, password, now)
            if user.locked_until is not None and user.locked_until > now:
                await _verify(user.password_hash, password)  # same work as an unlocked attempt
                self._audit(session, user.id, "staff.login", {}, ResultCode.ACCOUNT_LOCKED)
                return LoginResult(ResultCode.ACCOUNT_LOCKED, locked_until=user.locked_until)
            if not await _verify(user.password_hash, password):
                state = _Failures(user.failed_attempts, user.first_failed_at, None)
                _register_failure(state, now)
                user.failed_attempts, user.first_failed_at = state.count, state.first_at
                if state.locked_until is not None:
                    user.locked_until = state.locked_until
                    self._audit(session, user.id, "staff.lockout", {}, ResultCode.ACCOUNT_LOCKED)
                self._audit(session, user.id, "staff.login", {}, ResultCode.UNAUTHENTICATED)
                return LoginResult(ResultCode.UNAUTHENTICATED)
            if _hasher.check_needs_rehash(user.password_hash):
                user.password_hash = await hash_password(password)
            user.failed_attempts, user.first_failed_at, user.locked_until = 0, None, None
            user.last_login_at = now
            token = secrets.token_urlsafe(32)
            staff_session = StaffSession(
                staff_user_id=user.id,
                token_hash=token_hash(token),
                expires_at=now + SESSION_ABSOLUTE,
                last_seen_at=now,
            )
            session.add(staff_session)
            await session.flush()
            self._audit(session, user.id, "staff.login", {}, ResultCode.OK)
            return LoginResult(ResultCode.OK, _principal(user, staff_session.id), token)

    async def _unknown_login(
        self, session: AsyncSession, username: str, password: str, now: datetime
    ) -> LoginResult:
        """Behaves exactly like a real account with a wrong password, lockout included."""
        await _verify(_DUMMY_HASH, password)
        key = username.strip().lower()
        if not key or len(key) > MAX_USERNAME_LENGTH:
            return LoginResult(ResultCode.UNAUTHENTICATED)  # cannot be a real username: nothing to track
        username_hash = hashlib.sha256(key.encode()).digest()
        await session.execute(
            insert(LoginFailure)
            .values(username_hash=username_hash)
            .on_conflict_do_nothing(index_elements=["username_hash"])
        )
        row = await session.get_one(LoginFailure, username_hash, with_for_update=True)
        row.updated_at = now
        if row.locked_until is not None and row.locked_until > now:
            self._audit(session, None, "staff.login", {}, ResultCode.ACCOUNT_LOCKED)
            return LoginResult(ResultCode.ACCOUNT_LOCKED, locked_until=row.locked_until)
        state = _Failures(row.failed_attempts, row.first_failed_at, None)
        _register_failure(state, now)
        row.failed_attempts, row.first_failed_at, row.locked_until = (
            state.count,
            state.first_at,
            state.locked_until,
        )
        await session.execute(delete(LoginFailure).where(LoginFailure.updated_at < now - FAILURE_RETENTION))
        self._audit(session, None, "staff.login", {}, ResultCode.UNAUTHENTICATED)
        return LoginResult(ResultCode.UNAUTHENTICATED)

    async def authenticate(self, token: str) -> StaffPrincipal | None:
        now = self._clock()
        async with self._session_factory() as session, session.begin():
            row = (
                await session.execute(
                    select(StaffSession, StaffUser)
                    .join(StaffUser, StaffUser.id == StaffSession.staff_user_id)
                    .where(StaffSession.token_hash == token_hash(token))
                )
            ).first()
            if row is None:
                return None
            staff_session, user = row
            if (
                staff_session.revoked_at is not None
                or staff_session.expires_at <= now
                or now - staff_session.last_seen_at > SESSION_IDLE
                or not user.active
            ):
                return None
            if now - staff_session.last_seen_at > SEEN_WRITE_INTERVAL:
                staff_session.last_seen_at = now
            return _principal(user, staff_session.id)

    async def logout(self, session_id: UUID) -> None:
        async with self._session_factory() as session, session.begin():
            staff_session = await session.get(StaffSession, session_id)
            if staff_session is not None and staff_session.revoked_at is None:
                staff_session.revoked_at = self._clock()
                self._audit(session, staff_session.staff_user_id, "staff.logout", {}, ResultCode.OK)

    @staticmethod
    def _audit(
        session: AsyncSession, actor_id: UUID | None, action: str, args: dict[str, str], result: str
    ) -> None:
        AuditService.record(
            session,
            actor_type="staff",
            actor_id=str(actor_id) if actor_id else None,
            action=action,
            args=args,
            result=result,
            patient_id=None,
            latency_ms=None,
        )
