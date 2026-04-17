import pytest

from packages.core.embedding.fake_embedder import FakeEmbedder


@pytest.fixture
def embedder() -> FakeEmbedder:
    return FakeEmbedder(dimension=128)


async def test_embed_query_returns_correct_dimension(embedder: FakeEmbedder) -> None:
    vector = await embedder.embed_query("hello world")
    assert len(vector) == 128


async def test_embed_query_is_deterministic(embedder: FakeEmbedder) -> None:
    v1 = await embedder.embed_query("test input")
    v2 = await embedder.embed_query("test input")
    assert v1 == v2


async def test_embed_query_different_inputs_differ(embedder: FakeEmbedder) -> None:
    v1 = await embedder.embed_query("input A")
    v2 = await embedder.embed_query("input B")
    assert v1 != v2


async def test_embed_documents_batch(embedder: FakeEmbedder) -> None:
    texts = ["one", "two", "three"]
    results = await embedder.embed_documents(texts)
    assert len(results) == 3
    for vec in results:
        assert len(vec) == 128


async def test_embed_query_is_unit_vector(embedder: FakeEmbedder) -> None:
    vector = await embedder.embed_query("normalize me")
    magnitude = sum(f * f for f in vector) ** 0.5
    assert abs(magnitude - 1.0) < 1e-6
