import httpx


class LocalEmbedder:
    """Embedder backed by a co-located TEI (Text Embeddings Inference) sidecar."""

    def __init__(self, *, base_url: str, model_id: str, dimension: int) -> None:
        self.model_id = model_id
        self.dimension = dimension
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(base_url=self._base_url, timeout=30.0)

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        response = await self._client.post(
            "/embed",
            json={"inputs": texts, "truncate": True},
        )
        response.raise_for_status()
        return response.json()

    async def embed_query(self, text: str) -> list[float]:
        results = await self.embed_documents([text])
        return results[0]

    async def close(self) -> None:
        await self._client.aclose()
