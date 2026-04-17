"""Initial schema — all tables, extensions, indexes.

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

# Embedding dimension — harrier-oss-v1 (27B, 5376-dim).
# Locked after model selection. Changing requires full re-embed.
EMBEDDING_DIM = 5376


def upgrade() -> None:
    # Extensions
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # --- universities ---
    op.create_table(
        "universities",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("domain", sa.Text(), nullable=False, unique=True),
        sa.Column(
            "config",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # --- documents ---
    op.create_table(
        "documents",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), primary_key=True),
        sa.Column(
            "university_id", sa.UUID(), sa.ForeignKey("universities.id"), nullable=False
        ),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("page_type", sa.Text(), nullable=False),
        sa.Column("raw_html_gcs_path", sa.Text(), nullable=True),
        sa.Column("last_crawled", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_modified", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
    )
    op.create_index(
        "uq_documents_university_url", "documents", ["university_id", "url"], unique=True
    )
    op.create_index(
        "ix_documents_university_page_type", "documents", ["university_id", "page_type"]
    )
    op.create_index(
        "ix_documents_university_last_crawled",
        "documents",
        ["university_id", "last_crawled"],
    )

    # --- chunks ---
    op.create_table(
        "chunks",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), primary_key=True),
        sa.Column(
            "document_id",
            sa.UUID(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("university_id", sa.UUID(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("heading_trail", sa.dialects.postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column(
            "metadata",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "last_verified",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_chunks_university_document", "chunks", ["university_id", "document_id"]
    )

    # embedding vector column
    op.execute(f"ALTER TABLE chunks ADD COLUMN embedding vector({EMBEDDING_DIM})")

    # tsvector generated column — weighted heading trail (A) + body text (B)
    op.execute("""
        ALTER TABLE chunks ADD COLUMN tsv tsvector
        GENERATED ALWAYS AS (
            setweight(to_tsvector('english', coalesce(array_to_string(heading_trail, ' '), '')), 'A') ||
            setweight(to_tsvector('english', text), 'B')
        ) STORED
    """)

    # chunk indexes
    op.execute(
        "CREATE INDEX ix_chunks_tsv ON chunks USING GIN (tsv)"
    )
    op.execute(
        "CREATE INDEX ix_chunks_embedding ON chunks "
        "USING HNSW (embedding vector_cosine_ops)"
    )
    op.execute(
        "CREATE INDEX ix_chunks_metadata ON chunks "
        "USING GIN (metadata jsonb_path_ops)"
    )

    # --- entities ---
    op.create_table(
        "entities",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), primary_key=True),
        sa.Column("university_id", sa.UUID(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "metadata",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "source_document_id",
            sa.UUID(),
            sa.ForeignKey("documents.id"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_entities_university_type", "entities", ["university_id", "entity_type"]
    )
    op.execute(
        "CREATE INDEX ix_entities_metadata ON entities "
        "USING GIN (metadata jsonb_path_ops)"
    )

    # entity embedding + partial HNSW index for supervisor search
    op.execute(f"ALTER TABLE entities ADD COLUMN embedding vector({EMBEDDING_DIM})")
    op.execute(
        "CREATE INDEX ix_entities_embedding_supervisor ON entities "
        "USING HNSW (embedding vector_cosine_ops) "
        "WHERE entity_type = 'supervisor'"
    )

    # --- conversations ---
    op.execute("""
        CREATE TABLE conversations (
            id UUID PRIMARY KEY DEFAULT uuidv7(),
            university_id UUID NOT NULL REFERENCES universities(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at TIMESTAMPTZ NOT NULL GENERATED ALWAYS AS (created_at + INTERVAL '14 days') STORED
        )
    """)
    op.create_index("ix_conversations_expires_at", "conversations", ["expires_at"])

    # --- messages ---
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
            "retrieved_chunk_ids",
            sa.dialects.postgresql.ARRAY(sa.UUID()),
            nullable=True,
        ),
        sa.Column(
            "metadata",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # --- sessions ---
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

    # --- api_keys ---
    op.create_table(
        "api_keys",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), primary_key=True),
        sa.Column(
            "university_id", sa.UUID(), sa.ForeignKey("universities.id"), nullable=False
        ),
        sa.Column("key_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_api_keys_key_hash", "api_keys", ["key_hash"])
    op.create_index("ix_api_keys_university", "api_keys", ["university_id"])

    # --- feedback ---
    op.create_table(
        "feedback",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), primary_key=True),
        sa.Column(
            "message_id",
            sa.UUID(),
            sa.ForeignKey("messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rating", sa.SmallInteger(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("feedback")
    op.drop_table("api_keys")
    op.drop_table("sessions")
    op.drop_table("messages")
    op.execute("DROP TABLE conversations")
    op.drop_table("entities")
    op.drop_table("chunks")
    op.drop_table("documents")
    op.drop_table("universities")
    op.execute("DROP EXTENSION IF EXISTS vector")
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
    op.execute("DROP EXTENSION IF EXISTS pgcrypto")
