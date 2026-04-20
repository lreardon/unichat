"""Change detection for documents — checks if a URL's content has changed since last crawl."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from packages.core.models import Document


class ChangeDetector:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def should_process(
        self,
        university_id: uuid.UUID,
        url: str,
        content_hash: str,
    ) -> bool:
        """Return True if this content is new or changed (hash mismatch)."""
        async with self._session_factory() as session:
            result = await session.execute(
                select(Document.content_hash).where(
                    Document.university_id == university_id,
                    Document.url == url,
                    Document.status == "active",
                )
            )
            existing_hash = result.scalar_one_or_none()
            return existing_hash != content_hash
