"""Make documents.page_type nullable.

Revision ID: 004
Revises: 003
Create Date: 2026-04-20
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("documents", "page_type", existing_type=sa.Text(), nullable=True)


def downgrade() -> None:
    op.execute("UPDATE documents SET page_type = 'general' WHERE page_type IS NULL")
    op.alter_column("documents", "page_type", existing_type=sa.Text(), nullable=False)
