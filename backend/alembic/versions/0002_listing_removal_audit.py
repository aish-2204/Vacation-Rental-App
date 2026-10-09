"""Retain actor and reason for terminal listing removals, including Host actions."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002_listing_removal_audit"
down_revision: str | Sequence[str] | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "listing_removals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("listing_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_listing_removals")),
        sa.ForeignKeyConstraint(
            ["listing_id"],
            ["listings.id"],
            ondelete="RESTRICT",
            name=op.f("fk_listing_removals_listing_id_listings"),
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
            ondelete="RESTRICT",
            name=op.f("fk_listing_removals_actor_id_users"),
        ),
        sa.UniqueConstraint("listing_id", name=op.f("uq_listing_removals_listing_id")),
        sa.CheckConstraint(
            "length(btrim(reason)) > 0", name=op.f("ck_listing_removals_nonempty_reason")
        ),
    )
    # Existing removals are retained unchanged. Do not invent historical actors
    # or reasons when that information was not recorded by the original schema.


def downgrade() -> None:
    op.drop_table("listing_removals")
