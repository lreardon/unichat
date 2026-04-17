from typing import Protocol, runtime_checkable


@runtime_checkable
class Embedder(Protocol):
    dimension: int
    model_id: str

    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    async def embed_query(self, text: str) -> list[float]: ...
