"""A deleted patient keeps no phone or Telegram ID (E1-S4-AC2/AC3, GAP-25).

Makes the anonymisation rule structural, so a soft-deleted record can never match a phone or
Telegram lookup and be re-linked, and its identifiers never block a new registration.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-03
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE patients ADD CONSTRAINT ck_patients_deleted_anonymised "
        "CHECK (deleted_at IS NULL OR (phone IS NULL AND telegram_user_id IS NULL))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE patients DROP CONSTRAINT ck_patients_deleted_anonymised")
