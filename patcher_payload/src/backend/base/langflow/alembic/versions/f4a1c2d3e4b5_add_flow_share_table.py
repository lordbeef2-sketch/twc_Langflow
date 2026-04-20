"""add_flow_share_table

Revision ID: f4a1c2d3e4b5
Revises: d306e5c17c41
Create Date: 2026-04-18 14:25:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f4a1c2d3e4b5"
down_revision: str | Sequence[str] | None = "d306e5c17c41"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "flow_share",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("flow_id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("recipient_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "permission",
            sa.Enum("read", "edit", name="flow_share_permission_enum"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum("pending", "accepted", "rejected", name="flow_share_status_enum"),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["flow_id"], ["flow.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recipient_user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("flow_id", "recipient_user_id", name="uq_flow_share_flow_recipient"),
    )
    with op.batch_alter_table("flow_share", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_flow_share_flow_id"), ["flow_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_flow_share_owner_user_id"), ["owner_user_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_flow_share_recipient_user_id"), ["recipient_user_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("flow_share", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_flow_share_recipient_user_id"))
        batch_op.drop_index(batch_op.f("ix_flow_share_owner_user_id"))
        batch_op.drop_index(batch_op.f("ix_flow_share_flow_id"))

    op.drop_table("flow_share")
