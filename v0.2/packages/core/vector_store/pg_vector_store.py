import uuid

from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from packages.core.vector_store.vector_store import ChunkResult


class PgVectorStore:
    """VectorStore implementation backed by pgvector on PostgreSQL."""

    def __init__(self, *, session_factory: object, dimension: int) -> None:
        self._session_factory = session_factory
        self._dimension = dimension

    async def upsert(
        self,
        *,
        chunk_id: uuid.UUID,
        document_id: uuid.UUID,
        university_id: uuid.UUID,
        content: str,
        embedding: list[float],
        chunk_index: int,
        metadata_json: str | None = None,
    ) -> None:
        async with self._session_factory() as session:
            session: AsyncSession
            await session.execute(
                text("""
                    INSERT INTO chunks (id, document_id, university_id, content, chunk_index, metadata_json, embedding)
                    VALUES (:id, :document_id, :university_id, :content, :chunk_index, :metadata_json, :embedding)
                    ON CONFLICT (id) DO UPDATE SET
                        content = EXCLUDED.content,
                        embedding = EXCLUDED.embedding,
                        metadata_json = EXCLUDED.metadata_json
                """),
                {
                    "id": chunk_id,
                    "document_id": document_id,
                    "university_id": university_id,
                    "content": content,
                    "chunk_index": chunk_index,
                    "metadata_json": metadata_json,
                    "embedding": str(embedding),
                },
            )
            await session.commit()

    async def search(
        self,
        *,
        university_id: uuid.UUID,
        query_embedding: list[float],
        top_k: int = 10,
    ) -> list[ChunkResult]:
        async with self._session_factory() as session:
            session: AsyncSession
            rows = await session.execute(
                text("""
                    SELECT id, document_id, content, metadata_json,
                           1 - (embedding <=> :query_embedding::vector) AS score
                    FROM chunks
                    WHERE university_id = :university_id
                    ORDER BY embedding <=> :query_embedding::vector
                    LIMIT :top_k
                """),
                {
                    "university_id": university_id,
                    "query_embedding": str(query_embedding),
                    "top_k": top_k,
                },
            )
            return [
                ChunkResult(
                    chunk_id=row.id,
                    document_id=row.document_id,
                    content=row.content,
                    score=row.score,
                    metadata_json=row.metadata_json,
                )
                for row in rows
            ]

    async def delete_by_document(self, *, document_id: uuid.UUID) -> int:
        async with self._session_factory() as session:
            session: AsyncSession
            result = await session.execute(
                delete(text("chunks")).where(text("document_id = :doc_id")),
                {"doc_id": document_id},
            )
            await session.commit()
            return result.rowcount
