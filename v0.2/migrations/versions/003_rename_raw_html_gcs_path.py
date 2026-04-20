"""Rename raw_html_gcs_path to raw_html_path in documents table.

Revision ID: 003
Revises: 002
Create Date: 2026-04-17
"""

from typing import Sequence, Union

from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("documents", "raw_html_gcs_path", new_column_name="raw_html_path")


def downgrade() -> None:
    op.alter_column("documents", "raw_html_path", new_column_name="raw_html_gcs_path")
