"""Initial schema with extensions and all tables.

Revision ID: 001
Revises: None
Create Date: 2026-04-17
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Embedding dimension — locked after Phase 1 bake-off.
# Default: 1024 (Qwen3-Embedding-0.6B / BGE-M3).
EMBEDDING_DIM = 1024


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "universities",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False, unique=True),
        sa.Column("domain", sa.Text(), nullable=False),
        sa.Column("api_key_hash", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_table(
        "conversations",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), primary_key=True),
        sa.Column(
            "university_id", sa.UUID(), sa.ForeignKey("universities.id"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now() + interval '14 days'"),
        ),
    )
    op.create_index("ix_conversations_expires_at", "conversations", ["expires_at"])

    op.create_table(
        "sessions",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), primary_key=True),
        sa.Column(
            "university_id", sa.UUID(), sa.ForeignKey("universities.id"), nullable=False
        ),
        sa.Column("token_hash", sa.Text(), nullable=False, unique=True),
        sa.Column(
            "conversation_id",
            sa.UUID(),
            sa.ForeignKey("conversations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_sessions_expires_at", "sessions", ["expires_at"])
    op.create_index("ix_sessions_token_hash", "sessions", ["token_hash"])
    op.create_index(
        "ix_sessions_university_last_seen", "sessions", ["university_id", "last_seen_at"]
    )

    op.create_table(
        "messages",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.UUID(),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_messages_conversation_created", "messages", ["conversation_id", "created_at"]
    )

    op.create_table(
        "feedback",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), primary_key=True),
        sa.Column(
            "message_id",
            sa.UUID(),
            sa.ForeignKey("messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_table(
        "documents",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), primary_key=True),
        sa.Column(
            "university_id", sa.UUID(), sa.ForeignKey("universities.id"), nullable=False
        ),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column(
            "crawled_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_documents_university_url", "documents", ["university_id", "url"], unique=True
    )

    op.create_table(
        "chunks",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), primary_key=True),
        sa.Column(
            "document_id",
            sa.UUID(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "university_id", sa.UUID(), sa.ForeignKey("universities.id"), nullable=False
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=True),
    )
    op.create_index("ix_chunks_document_index", "chunks", ["document_id", "chunk_index"])
    op.create_index("ix_chunks_university", "chunks", ["university_id"])

    # Add embedding vector column — dimension set by EMBEDDING_DIM constant
    op.execute(
        f"ALTER TABLE chunks ADD COLUMN embedding vector({EMBEDDING_DIM})"
    )
    # HNSW index for cosine similarity with tenant filter
    op.execute(
        "CREATE INDEX ix_chunks_embedding ON chunks "
        "USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.drop_table("chunks")
    op.drop_table("documents")
    op.drop_table("feedback")
    op.drop_table("messages")
    op.drop_table("sessions")
    op.drop_table("conversations")
    op.drop_table("universities")
    op.execute("DROP EXTENSION IF EXISTS vector")
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
    op.execute("DROP EXTENSION IF EXISTS pgcrypto")
