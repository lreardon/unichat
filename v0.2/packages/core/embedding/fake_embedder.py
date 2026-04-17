import hashlib
import struct


class FakeEmbedder:
    """Deterministic hash-based embedder for tests. No external dependencies."""

    def __init__(self, *, dimension: int = 1024, model_id: str = "fake") -> None:
        self.dimension = dimension
        self.model_id = model_id

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._hash_to_vector(t) for t in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._hash_to_vector(text)

    def _hash_to_vector(self, text: str) -> list[float]:
        digest = hashlib.sha512(text.encode()).digest()
        # Extend digest to fill dimension by repeating
        needed_bytes = self.dimension * 4
        extended = digest * (needed_bytes // len(digest) + 1)
        floats = struct.unpack(f"<{self.dimension}f", extended[: needed_bytes])
        # Normalize to unit vector
        magnitude = sum(f * f for f in floats) ** 0.5
        if magnitude == 0:
            return [0.0] * self.dimension
        return [f / magnitude for f in floats]
