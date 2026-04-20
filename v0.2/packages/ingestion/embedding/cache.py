"""Content-hash-keyed embedding cache backed by Postgres."""

from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from packages.core.models import EmbeddingsCacheEntry


class EmbeddingCache:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        model_id: str,
    ) -> None:
        self._session_factory = session_factory
        self._model_id = model_id

    async def get_many(self, content_hashes: list[str]) -> dict[str, list[float]]:
        """Return {hash: embedding} for cache hits matching current model."""
        if not content_hashes:
            return {}

        async with self._session_factory() as session:
            result = await session.execute(
                select(
                    EmbeddingsCacheEntry.content_hash,
                    text("embedding::text"),
                ).where(
                    EmbeddingsCacheEntry.content_hash.in_(content_hashes),
                    EmbeddingsCacheEntry.model_id == self._model_id,
                )
            )
            hits: dict[str, list[float]] = {}
            for row in result:
                embedding_str = row[1]
                # pgvector returns "[0.1,0.2,...]" format
                embedding = [float(x) for x in embedding_str.strip("[]").split(",")]
                hits[row[0]] = embedding
            return hits

    async def put_many(self, entries: dict[str, list[float]]) -> None:
        """Upsert hash→embedding pairs."""
        if not entries:
            return

        async with self._session_factory() as session:
            for content_hash, embedding in entries.items():
                vec_str = "[" + ",".join(str(x) for x in embedding) + "]"
                await session.execute(
                    text("""
                        INSERT INTO embeddings_cache (content_hash, embedding, model_id)
                        VALUES (:hash, CAST(:embedding AS vector), :model_id)
                        ON CONFLICT (content_hash) DO UPDATE
                        SET embedding = EXCLUDED.embedding,
                            model_id = EXCLUDED.model_id
                    """),
                    {"hash": content_hash, "embedding": vec_str, "model_id": self._model_id},
                )
            await session.commit()
