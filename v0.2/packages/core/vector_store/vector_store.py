import uuid
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class ChunkResult:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    content: str
    score: float
    metadata_json: str | None = None


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
        chunk_index: int,
        metadata_json: str | None = None,
    ) -> None: ...

    async def search(
        self,
        *,
        university_id: uuid.UUID,
        query_embedding: list[float],
        top_k: int = 10,
    ) -> list[ChunkResult]: ...

    async def delete_by_document(self, *, document_id: uuid.UUID) -> int: ...
