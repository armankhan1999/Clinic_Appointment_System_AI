"""Lockout state for unknown staff usernames, stored like real accounts' (E6-S1-AC3, no enumeration).

Keyed by SHA-256 of the normalised username, so attempted usernames are never stored in clear. Shared by
every API process and kept across restarts, exactly like the lockout columns on staff_users.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-04
"""

import re
from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def _app_role() -> str:
    config = op.get_context().config
    if config is None:
        raise RuntimeError("run migrations through the Alembic command line (env.py sets the target)")
    role: str = config.attributes["app_role"]
    if not _IDENTIFIER.match(role):
        raise ValueError(f"unsafe identifier {role!r}")
    return role


def upgrade() -> None:
    op.execute(
        "CREATE TABLE login_failures ("
        " username_hash bytea NOT NULL,"
        " failed_attempts smallint NOT NULL DEFAULT 0,"
        " first_failed_at timestamptz,"
        " locked_until timestamptz,"
        " updated_at timestamptz NOT NULL DEFAULT now(),"
        " CONSTRAINT pk_login_failures PRIMARY KEY (username_hash),"
        " CONSTRAINT ck_login_failures_attempts CHECK (failed_attempts >= 0))"
    )
    op.execute("CREATE INDEX ix_login_failures_updated_at ON login_failures (updated_at)")
    op.execute("ALTER TABLE login_failures ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY app_access ON login_failures FOR ALL TO {_app_role()} USING (true) WITH CHECK (true)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE login_failures")
