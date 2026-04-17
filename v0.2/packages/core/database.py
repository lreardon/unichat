from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from packages.core.config import Settings


def create_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        settings.database_url,
        pool_size=20,
        max_overflow=10,
    )


def create_session_factory(engine: AsyncEngine) -> sessionmaker[AsyncSession]:
    return sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
