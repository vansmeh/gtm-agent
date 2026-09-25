"""person opportunities

Revision ID: d8f3b12c6a44
Revises: c7e2a91b4d10
Create Date: 2026-09-24 09:40:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d8f3b12c6a44"
down_revision: str | None = "c7e2a91b4d10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "person_opportunities",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("person_id", sa.String(length=36), nullable=False),
        sa.Column("technical_problem", sa.Text(), nullable=False),
        sa.Column("signal_ids_json", sa.Text(), nullable=False),
        sa.Column("evidence_ids_json", sa.Text(), nullable=False),
        sa.Column("supporting_evidence_ids_json", sa.Text(), nullable=False),
        sa.Column("contradicting_evidence_ids_json", sa.Text(), nullable=False),
        sa.Column("person_fit_json", sa.Text(), nullable=False),
        sa.Column("why_now", sa.Text(), nullable=False),
        sa.Column("redis_hypothesis", sa.Text(), nullable=False),
        sa.Column("alternative_technologies_json", sa.Text(), nullable=False),
        sa.Column("contactability_json", sa.Text(), nullable=False),
        sa.Column("recommended_channel", sa.String(length=40), nullable=False),
        sa.Column("decision", sa.String(length=40), nullable=False),
        sa.Column("template_id", sa.String(length=80), nullable=True),
        sa.Column("action_id", sa.String(length=36), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("person_kind", sa.String(length=40), nullable=False),
        sa.Column("thread_role", sa.String(length=40), nullable=False),
        sa.Column("angle", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["research_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("person_opportunities")
