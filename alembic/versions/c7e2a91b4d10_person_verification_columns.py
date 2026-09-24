"""person verification columns

Revision ID: c7e2a91b4d10
Revises: b61917a8b603
Create Date: 2026-09-24 09:20:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c7e2a91b4d10"
down_revision: str | None = "b61917a8b603"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("people", sa.Column("company", sa.String(length=200), nullable=False, server_default=""))
    op.add_column("people", sa.Column("identity_excerpt", sa.Text(), nullable=False, server_default=""))
    op.add_column(
        "people",
        sa.Column("responsibility_status", sa.String(length=20), nullable=False, server_default="unknown"),
    )
    op.add_column(
        "people",
        sa.Column("selection_status", sa.String(length=40), nullable=False, server_default="weak_candidate"),
    )
    op.add_column("people", sa.Column("first_seen", sa.String(length=20), nullable=True))
    op.add_column("people", sa.Column("last_seen", sa.String(length=20), nullable=True))
    op.add_column("people", sa.Column("role_published_at", sa.String(length=20), nullable=True))
    op.add_column("people", sa.Column("validity", sa.String(length=20), nullable=False, server_default="unknown"))
    op.add_column("people", sa.Column("contradictions_json", sa.Text(), nullable=False, server_default="[]"))


def downgrade() -> None:
    for name in (
        "contradictions_json",
        "validity",
        "role_published_at",
        "last_seen",
        "first_seen",
        "selection_status",
        "responsibility_status",
        "identity_excerpt",
        "company",
    ):
        op.drop_column("people", name)
