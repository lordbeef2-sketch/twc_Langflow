"""add_can_view_all_flows_to_user

Revision ID: a7c9d4e1f0b2
Revises: f4a1c2d3e4b5
Create Date: 2026-06-12 03:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7c9d4e1f0b2"
down_revision: str | Sequence[str] | None = "f4a1c2d3e4b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    user_columns = {column["name"] for column in inspector.get_columns("user")}
    if "can_view_all_flows" in user_columns:
        return

    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "can_view_all_flows",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    user_columns = {column["name"] for column in inspector.get_columns("user")}
    if "can_view_all_flows" not in user_columns:
        return

    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.drop_column("can_view_all_flows")
