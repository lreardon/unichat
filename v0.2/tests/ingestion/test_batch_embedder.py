"""Tests for batch embedder with mock embedder and cache."""

from unittest.mock import AsyncMock

from packages.ingestion.embedding.batch_embedder import BatchEmbedder
from packages.ingestion.extraction.models import ExtractedChunk


class FakeCache:
    def __init__(self) -> None:
        self._store: dict[str, list[float]] = {}

    async def get_many(self, hashes: list[str]) -> dict[str, list[float]]:
        return {h: self._store[h] for h in hashes if h in self._store}

    async def put_many(self, entries: dict[str, list[float]]) -> None:
        self._store.update(entries)


def _make_chunk(text: str, trail: list[str] | None = None) -> ExtractedChunk:
    return ExtractedChunk(
        text=text,
        position=0,
        heading_trail=trail or [],
    )


async def test_embeds_all_chunks() -> None:
    embedder = AsyncMock()
    embedder.embed_documents = AsyncMock(return_value=[[0.1, 0.2], [0.3, 0.4]])
    embedder.model_id = "test-model"
    embedder.dimension = 2

    cache = FakeCache()
    batch_embedder = BatchEmbedder(embedder=embedder, cache=cache, batch_size=128)

    chunks = [_make_chunk("hello world"), _make_chunk("goodbye world")]
    result = await batch_embedder.embed_chunks(chunks)

    assert len(result) == 2
    assert result[0] == [0.1, 0.2]
    assert result[1] == [0.3, 0.4]
    embedder.embed_documents.assert_called_once()


async def test_cache_hit_skips_embedding() -> None:
    embedder = AsyncMock()
    embedder.model_id = "test-model"
    embedder.dimension = 2

    cache = FakeCache()
    batch_embedder = BatchEmbedder(embedder=embedder, cache=cache, batch_size=128)

    # First call — cache miss
    embedder.embed_documents = AsyncMock(return_value=[[0.1, 0.2]])
    chunks = [_make_chunk("hello world")]
    await batch_embedder.embed_chunks(chunks)

    # Second call — same content should hit cache
    embedder.embed_documents = AsyncMock(return_value=[])
    result = await batch_embedder.embed_chunks(chunks)

    assert len(result) == 1
    assert result[0] == [0.1, 0.2]
    embedder.embed_documents.assert_not_called()


async def test_heading_trail_prefix() -> None:
    embedder = AsyncMock()
    embedder.embed_documents = AsyncMock(return_value=[[0.1]])
    embedder.model_id = "test-model"
    embedder.dimension = 2

    cache = FakeCache()
    batch_embedder = BatchEmbedder(embedder=embedder, cache=cache, batch_size=128)

    chunks = [_make_chunk("content here", trail=["Programs", "MSc CS"])]
    await batch_embedder.embed_chunks(chunks)

    # Check that the text passed to the embedder includes the heading trail prefix
    call_args = embedder.embed_documents.call_args[0][0]
    assert "Programs > MSc CS" in call_args[0]
    assert "content here" in call_args[0]


async def test_batching() -> None:
    call_count = 0

    async def mock_embed(texts: list[str]) -> list[list[float]]:
        nonlocal call_count
        call_count += 1
        return [[0.1] * 2 for _ in texts]

    embedder = AsyncMock()
    embedder.embed_documents = mock_embed
    embedder.model_id = "test-model"
    embedder.dimension = 2

    cache = FakeCache()
    batch_embedder = BatchEmbedder(embedder=embedder, cache=cache, batch_size=2)

    chunks = [_make_chunk(f"chunk {i}") for i in range(5)]
    result = await batch_embedder.embed_chunks(chunks)

    assert len(result) == 5
    assert call_count == 3  # 2 + 2 + 1
