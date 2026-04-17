from packages.core.embedding.embedder import Embedder
from packages.core.embedding.fake_embedder import FakeEmbedder
from packages.core.embedding.local_embedder import LocalEmbedder
from packages.core.embedding.remote_embedder import RemoteEmbedder


def test_fake_embedder_satisfies_protocol() -> None:
    assert isinstance(FakeEmbedder(dimension=64), Embedder)


def test_local_embedder_satisfies_protocol() -> None:
    embedder = LocalEmbedder(base_url="http://localhost:8080", model_id="test", dimension=64)
    assert isinstance(embedder, Embedder)


def test_remote_embedder_satisfies_protocol() -> None:
    embedder = RemoteEmbedder(base_url="http://localhost:8080", model_id="test", dimension=64)
    assert isinstance(embedder, Embedder)
