import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class ChunkResult:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    content: str
    score: float
    heading_trail: list[str] | None = None
    metadata: dict[str, Any] | None = field(default=None)


@runtime_checkable
class VectorStore(Protocol):
    async def upsert(
        self,
        *,
        chunk_id: uuid.UUID,
        document_id: uuid.UUID,
        university_id: uuid.UUID,
        content: str,
        embedding: list[float],
        position: int,
        heading_trail: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None: ...

    async def search(
        self,
        *,
        university_id: uuid.UUID,
        query_embedding: list[float],
        top_k: int = 10,
    ) -> list[ChunkResult]: ...

    async def delete_by_document(self, *, document_id: uuid.UUID) -> int: ...
