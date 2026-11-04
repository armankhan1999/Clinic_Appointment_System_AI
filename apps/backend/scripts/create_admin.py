"""Create a staff admin account from the command line; the password is typed twice and never echoed.

    uv run python scripts/create_admin.py --target dev --username owner --display-name "Clinic Owner"

Bootstraps the first admin (IMP-04). Further accounts are managed in the dashboard.
"""

import argparse
import asyncio
import getpass
import sys
from collections.abc import Callable

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from clinic.config import DbTarget, get_settings
from clinic.db.session import make_engine, make_session_factory
from clinic.services.booking import constraint_name
from clinic.services.staff_auth import InvalidUsernameError, StaffAuthService, WeakPasswordError


class AdminBootstrapError(Exception):
    """A user-facing reason the account was not created."""


def read_password(prompt: Callable[[str], str] = getpass.getpass) -> str:
    first = prompt("Password (12+ characters, not shown): ")
    if prompt("Type it again: ") != first:
        raise AdminBootstrapError("The two passwords did not match. Nothing was created.")
    return first


async def create_admin(
    session_factory: async_sessionmaker[AsyncSession],
    secret: bytes,
    username: str,
    display_name: str,
    password: str,
) -> None:
    auth = StaffAuthService(session_factory, secret=secret)
    try:
        await auth.create_user(
            username=username, display_name=display_name, role="admin", password=password, actor_id=None
        )
    except (WeakPasswordError, InvalidUsernameError) as exc:
        raise AdminBootstrapError(f"Not created: {exc}.") from exc
    except IntegrityError as exc:
        if constraint_name(exc) != "ux_staff_users_username_lower":
            raise
        raise AdminBootstrapError(f"Not created: the username {username!r} already exists.") from exc


async def _main(target_name: str, username: str, display_name: str) -> int:
    settings = get_settings()
    target = DbTarget.app(settings) if target_name == "dev" else DbTarget.test(settings)
    try:
        password = read_password()
    except AdminBootstrapError as exc:
        print(exc, file=sys.stderr)
        return 1
    engine = make_engine(target, settings, null_pool=True)
    try:
        await create_admin(
            make_session_factory(engine),
            settings.auth_secret.get_secret_value().encode(),
            username,
            display_name,
            password,
        )
    except AdminBootstrapError as exc:
        print(exc, file=sys.stderr)
        return 1
    finally:
        await engine.dispose()
    print(f"Admin {username.strip().lower()!r} created in schema '{target.schema}'.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--target", choices=("dev", "test"), required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--display-name", required=True)
    args = parser.parse_args()
    sys.exit(asyncio.run(_main(args.target, args.username, args.display_name)))
