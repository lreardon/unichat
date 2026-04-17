from __future__ import annotations

import hashlib
import importlib
import logging
import math
import re
from collections import Counter


_WORD_RE = re.compile(r"[a-zA-Z0-9]+")
_LOGGER = logging.getLogger(__name__)


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in _WORD_RE.findall(text)]


class EmbeddingProvider:
    def embed(self, text: str) -> list[float]:
        raise NotImplementedError


class HashingEmbeddingProvider(EmbeddingProvider):
    def __init__(self, dimensions: int = 256) -> None:
        self.dimensions = dimensions

    @staticmethod
    def tokenize(text: str) -> list[str]:
        return tokenize(text)

    def embed(self, text: str) -> list[float]:
        counts = Counter(self.tokenize(text))
        vector = [0.0] * self.dimensions
        if not counts:
            return vector

        for token, tf in counts.items():
            digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
            index = int(digest[:8], 16) % self.dimensions
            sign = -1.0 if int(digest[8:10], 16) % 2 else 1.0
            weight = 1.0 + math.log(float(tf))
            vector[index] += sign * weight

        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0.0:
            return vector
        return [v / norm for v in vector]


class SentenceTransformerEmbeddingProvider(EmbeddingProvider):
    def __init__(
        self,
        *,
        model_name: str,
        output_dimensions: int,
        allow_download: bool,
    ) -> None:
        self.model_name = model_name
        self.output_dimensions = output_dimensions
        sentence_transformers = importlib.import_module("sentence_transformers")
        sentence_transformer_cls = getattr(sentence_transformers, "SentenceTransformer")
        self._model = sentence_transformer_cls(model_name, local_files_only=(not allow_download))
        self._projection = None

    def _project_if_needed(self, vector: list[float]) -> list[float]:
        source_dim = len(vector)
        if source_dim == self.output_dimensions:
            return vector

        if source_dim > self.output_dimensions:
            try:
                import numpy as np
            except ImportError:
                return vector[: self.output_dimensions]

            if self._projection is None:
                seed = int(hashlib.sha256(f"{self.model_name}:{self.output_dimensions}".encode("utf-8")).hexdigest()[:8], 16)
                rng = np.random.default_rng(seed)
                projection = rng.standard_normal((source_dim, self.output_dimensions), dtype=np.float32)
                projection /= math.sqrt(self.output_dimensions)
                self._projection = projection

            projected = np.asarray(vector, dtype=np.float32) @ self._projection
            norm = float(np.linalg.norm(projected))
            if norm == 0.0:
                return projected.tolist()
            return (projected / norm).tolist()

        padded = vector + ([0.0] * (self.output_dimensions - source_dim))
        norm = math.sqrt(sum(v * v for v in padded))
        if norm == 0.0:
            return padded
        return [v / norm for v in padded]

    def embed(self, text: str) -> list[float]:
        vector = self._model.encode(text, normalize_embeddings=True).tolist()
        if isinstance(vector[0], list):
            vector = vector[0]
        return self._project_if_needed(vector)


def build_embedding_provider(
    *,
    backend: str,
    dimensions: int,
    model_name: str,
    allow_download: bool,
) -> EmbeddingProvider:
    normalized_backend = backend.strip().lower()
    if normalized_backend == "hashing":
        return HashingEmbeddingProvider(dimensions=dimensions)

    if normalized_backend in {"auto", "sentence-transformers", "sentence_transformers", "st"}:
        try:
            return SentenceTransformerEmbeddingProvider(
                model_name=model_name,
                output_dimensions=dimensions,
                allow_download=allow_download,
            )
        except Exception as exc:  # pragma: no cover - depends on runtime model env
            if normalized_backend != "auto":
                raise
            _LOGGER.warning(
                "Falling back to hashing embeddings because sentence-transformers initialization failed: %s",
                exc,
            )
            return HashingEmbeddingProvider(dimensions=dimensions)

    raise ValueError(f"Unsupported embedding backend: {backend}")


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        raise ValueError("Vector size mismatch")
    return sum(x * y for x, y in zip(a, b))
