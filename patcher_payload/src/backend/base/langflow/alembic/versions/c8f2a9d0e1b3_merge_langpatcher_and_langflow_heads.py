"""merge_langpatcher_and_langflow_heads

Revision ID: c8f2a9d0e1b3
Revises: a7c9d4e1f0b2, b7c4d8e9f012
Create Date: 2026-06-12 10:15:00.000000
"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "c8f2a9d0e1b3"
down_revision: str | Sequence[str] | None = ("a7c9d4e1f0b2", "b7c4d8e9f012")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
