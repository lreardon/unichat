from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import sessionmaker

from packages.core.config import Settings
from packages.core.database import create_engine, create_session_factory
from packages.core.embedding.embedder import Embedder
from packages.core.embedding.fake_embedder import FakeEmbedder
from packages.core.embedding.local_embedder import LocalEmbedder
from packages.core.embedding.remote_embedder import RemoteEmbedder
from packages.core.vector_store.pg_vector_store import PgVectorStore
from packages.core.vector_store.vector_store import VectorStore


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


_engine: AsyncEngine | None = None
_session_factory: sessionmaker[AsyncSession] | None = None
_embedder: Embedder | None = None
_vector_store: VectorStore | None = None


async def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_engine(get_settings())
    return _engine


async def get_session_factory() -> sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        engine = await get_engine()
        _session_factory = create_session_factory(engine)
    return _session_factory


async def get_db_session() -> AsyncSession:
    factory = await get_session_factory()
    async with factory() as session:
        yield session


def build_embedder(settings: Settings) -> Embedder:
    match settings.embedder_type:
        case "local":
            return LocalEmbedder(
                base_url=settings.embedder_url,
                model_id=settings.embedding_model_id,
                dimension=settings.embedding_dimension,
            )
        case "remote":
            return RemoteEmbedder(
                base_url=settings.embedder_url,
                model_id=settings.embedding_model_id,
                dimension=settings.embedding_dimension,
            )
        case "fake":
            return FakeEmbedder(
                dimension=settings.embedding_dimension,
            )
        case unknown:
            raise ValueError(f"Unknown embedder type: {unknown!r}")


async def get_embedder() -> Embedder:
    global _embedder
    if _embedder is None:
        _embedder = build_embedder(get_settings())
    return _embedder


async def get_vector_store() -> VectorStore:
    global _vector_store
    if _vector_store is None:
        factory = await get_session_factory()
        settings = get_settings()
        _vector_store = PgVectorStore(
            session_factory=factory,
            dimension=settings.embedding_dimension,
        )
    return _vector_store
