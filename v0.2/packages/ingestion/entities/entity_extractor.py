"""LLM-based entity extraction using Claude Haiku with structured output."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

import anthropic
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from packages.core.models import Entity
from packages.ingestion.entities.prompts import (
    ENTITY_EXTRACTION_SYSTEM,
    ENTITY_EXTRACTION_USER,
)

logger = logging.getLogger(__name__)


class EntityExtractor:
    def __init__(
        self,
        *,
        api_key: str,
        model: str = "claude-haiku-4-20250414",
        batch_size: int = 20,
        session_factory: async_sessionmaker[AsyncSession],
        extractor_version: str = "v1",
    ) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model
        self._batch_size = batch_size
        self._session_factory = session_factory
        self._version = extractor_version

    async def extract_from_chunks(
        self,
        chunks: list[tuple[uuid.UUID, str]],
        university_id: uuid.UUID,
        source_document_id: uuid.UUID,
    ) -> int:
        """Extract entities from chunks and write to DB.

        Args:
            chunks: List of (chunk_id, text) tuples.
            university_id: Tenant ID.
            source_document_id: Document these chunks belong to.

        Returns:
            Number of entities extracted.
        """
        total = 0
        for batch_start in range(0, len(chunks), self._batch_size):
            batch = chunks[batch_start : batch_start + self._batch_size]
            entities = await self._extract_batch(batch)
            await self._store_entities(entities, university_id, source_document_id)
            total += len(entities)
        return total

    async def _extract_batch(
        self, chunks: list[tuple[uuid.UUID, str]]
    ) -> list[dict[str, Any]]:
        """Call Claude Haiku to extract entities from a batch of chunks."""
        chunks_text = "\n\n".join(
            f"--- Chunk {i} ---\n{text}" for i, (_, text) in enumerate(chunks)
        )
        user_msg = ENTITY_EXTRACTION_USER.format(
            count=len(chunks), chunks=chunks_text
        )

        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=4096,
                system=ENTITY_EXTRACTION_SYSTEM,
                messages=[{"role": "user", "content": user_msg}],
            )
        except anthropic.APIError:
            logger.exception("Entity extraction API call failed")
            return []

        content = response.content[0].text if response.content else ""
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            logger.warning("Entity extraction returned invalid JSON: %s", content[:200])
            return []

        entities: list[dict[str, Any]] = []
        if isinstance(parsed, dict):
            for idx_str, entity_list in parsed.items():
                idx = int(idx_str)
                if idx < len(chunks):
                    chunk_id = chunks[idx][0]
                    for entity in entity_list:
                        entity["_chunk_id"] = str(chunk_id)
                        entities.append(entity)
        return entities

    async def _store_entities(
        self,
        entities: list[dict[str, Any]],
        university_id: uuid.UUID,
        source_document_id: uuid.UUID,
    ) -> None:
        """Write extracted entities to the entities table."""
        if not entities:
            return

        async with self._session_factory() as session:
            for entity_data in entities:
                entity_type = entity_data.get("entity_type", "")
                name = entity_data.get("name", "")
                if not entity_type or not name:
                    continue

                metadata = entity_data.get("metadata", {})
                metadata["extractor_version"] = self._version
                metadata["_chunk_id"] = entity_data.get("_chunk_id")

                entity = Entity(
                    university_id=university_id,
                    entity_type=entity_type,
                    name=name,
                    meta=metadata,
                    source_document_id=source_document_id,
                )
                session.add(entity)

            await session.commit()
