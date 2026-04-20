"""Add embeddings_cache table for content-hash-keyed embedding cache.

Revision ID: 002
Revises: 001
Create Date: 2026-04-17
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMBEDDING_DIM = 1024


def upgrade() -> None:
    op.create_table(
        "embeddings_cache",
        sa.Column("content_hash", sa.Text(), primary_key=True),
        sa.Column("model_id", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.execute(
        f"ALTER TABLE embeddings_cache ADD COLUMN embedding vector({EMBEDDING_DIM}) NOT NULL"
    )
    op.create_index("ix_embeddings_cache_model", "embeddings_cache", ["model_id"])


def downgrade() -> None:
    op.drop_table("embeddings_cache")
