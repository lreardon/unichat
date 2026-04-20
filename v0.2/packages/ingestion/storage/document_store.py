"""Document CRUD — upsert by (university_id, url), manage document lifecycle."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from packages.core.models import Chunk, Document


class DocumentStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def upsert_document(
        self,
        *,
        university_id: uuid.UUID,
        url: str,
        title: str | None,
        content_hash: str,
        raw_html_path: str | None,
        page_type: str | None = None,
        last_modified: datetime | None = None,
    ) -> tuple[uuid.UUID, bool]:
        """Upsert a document by (university_id, url).

        Returns (document_id, is_new_or_changed).
        If content_hash matches existing active doc, returns (id, False).
        """
        async with self._session_factory() as session:
            result = await session.execute(
                select(Document).where(
                    Document.university_id == university_id,
                    Document.url == url,
                )
            )
            existing = result.scalar_one_or_none()

            now = datetime.now(UTC)

            if existing is not None:
                if existing.content_hash == content_hash and existing.status == "active":
                    existing.last_crawled = now
                    await session.commit()
                    return existing.id, False

                existing.content_hash = content_hash
                existing.title = title
                existing.page_type = page_type
                existing.raw_html_path = raw_html_path
                existing.last_crawled = now
                existing.last_modified = last_modified
                existing.status = "active"
                await session.commit()
                return existing.id, True

            doc = Document(
                university_id=university_id,
                url=url,
                title=title,
                content_hash=content_hash,
                page_type=page_type,
                raw_html_path=raw_html_path,
                last_crawled=now,
                last_modified=last_modified,
                status="active",
            )
            session.add(doc)
            await session.flush()
            doc_id = doc.id
            await session.commit()
            return doc_id, True

    async def delete_chunks_for_document(self, document_id: uuid.UUID) -> int:
        """Delete all chunks for a document. Returns count deleted."""
        async with self._session_factory() as session:
            result = await session.execute(
                select(Chunk).where(Chunk.document_id == document_id)
            )
            chunks = result.scalars().all()
            count = len(chunks)
            for chunk in chunks:
                await session.delete(chunk)
            await session.commit()
            return count
