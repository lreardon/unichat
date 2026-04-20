"""Batched embedding with cache-first strategy and exponential backoff."""

from __future__ import annotations

import asyncio
import hashlib
import logging

import httpx

from packages.core.embedding.embedder import Embedder
from packages.ingestion.embedding.cache import EmbeddingCache
from packages.ingestion.extraction.models import ExtractedChunk

logger = logging.getLogger(__name__)


class BatchEmbedder:
    """Embed chunks with heading-trail prefix. Cache-first, batch remainder."""

    def __init__(
        self,
        *,
        embedder: Embedder,
        cache: EmbeddingCache,
        batch_size: int = 128,
        max_concurrency: int = 2,
        max_retries: int = 3,
    ) -> None:
        self._embedder = embedder
        self._cache = cache
        self._batch_size = batch_size
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._max_retries = max_retries

    async def embed_chunks(
        self, chunks: list[ExtractedChunk]
    ) -> list[list[float]]:
        """Embed chunks, using cache for hits and batching misses."""
        texts = [_prefixed_text(c) for c in chunks]
        hashes = [hashlib.sha256(t.encode()).hexdigest() for t in texts]

        # Check cache
        cached = await self._cache.get_many(hashes)
        logger.info("Embedding cache: %d hits / %d total", len(cached), len(hashes))

        # Identify misses
        miss_indices: list[int] = []
        miss_texts: list[str] = []
        for i, h in enumerate(hashes):
            if h not in cached:
                miss_indices.append(i)
                miss_texts.append(texts[i])

        # Embed misses in batches
        new_embeddings: dict[int, list[float]] = {}
        for batch_start in range(0, len(miss_texts), self._batch_size):
            batch_end = batch_start + self._batch_size
            batch = miss_texts[batch_start:batch_end]
            batch_indices = miss_indices[batch_start:batch_end]

            embeddings = await self._embed_with_adaptive_split(batch)
            for idx, emb in zip(batch_indices, embeddings, strict=True):
                new_embeddings[idx] = emb

        # Cache new embeddings
        if new_embeddings:
            cache_entries = {
                hashes[idx]: emb for idx, emb in new_embeddings.items()
            }
            await self._cache.put_many(cache_entries)

        # Assemble results in order
        result: list[list[float]] = []
        for i, h in enumerate(hashes):
            if h in cached:
                result.append(cached[h])
            else:
                result.append(new_embeddings[i])

        return result

    async def _embed_with_retry(self, texts: list[str]) -> list[list[float]]:
        """Call embedder with exponential backoff on failure."""
        async with self._semaphore:
            for attempt in range(self._max_retries):
                try:
                    return await self._embedder.embed_documents(texts)
                except Exception:
                    if attempt == self._max_retries - 1:
                        raise
                    wait = 2**attempt
                    logger.warning(
                        "Embedding attempt %d failed, retrying in %ds",
                        attempt + 1,
                        wait,
                    )
                    await asyncio.sleep(wait)
        raise RuntimeError("unreachable")

    async def _embed_with_adaptive_split(self, texts: list[str]) -> list[list[float]]:
        """Split batch on 422 responses (often payload/token limits) and retry smaller parts."""
        try:
            return await self._embed_with_retry(texts)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 422 or len(texts) <= 1:
                raise

            mid = len(texts) // 2
            logger.warning(
                "Embedding batch rejected (422), splitting %d -> %d + %d",
                len(texts),
                mid,
                len(texts) - mid,
            )

            left = await self._embed_with_adaptive_split(texts[:mid])
            right = await self._embed_with_adaptive_split(texts[mid:])
            return left + right


def _prefixed_text(chunk: ExtractedChunk) -> str:
    """Prepend heading trail to chunk text for better retrieval."""
    if chunk.heading_trail:
        prefix = " > ".join(chunk.heading_trail)
        return f"{prefix}\n\n{chunk.text}"
    return chunk.text
