import pytest
from fastapi.testclient import TestClient

from packages.api.app import create_app
from packages.core.config import Settings
from packages.core.embedding.fake_embedder import FakeEmbedder


@pytest.fixture
def settings() -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://unichat:unichat@localhost:5432/unichat_test",
        embedder_type="fake",
        embedding_dimension=128,
    )


@pytest.fixture
def fake_embedder() -> FakeEmbedder:
    return FakeEmbedder(dimension=128)


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app)
