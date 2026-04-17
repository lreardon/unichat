from __future__ import annotations

from dataclasses import dataclass
import importlib
import logging
import math
from typing import Sequence

from rag.config import RagQueryConfig
from rag.embedding import HashingEmbeddingProvider, cosine_similarity
from rag.index_store import RagIndex
from rag.types import SearchResult


_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class _Candidate:
    index: int
    dense: float
    sparse: float
    combined: float


class HeuristicReranker:
    def score(self, question: str, text: str, heading: str) -> float:
        q_tokens = set(HashingEmbeddingProvider.tokenize(question))
        if not q_tokens:
            return 0.0
        text_tokens = HashingEmbeddingProvider.tokenize(text)
        if not text_tokens:
            return 0.0

        overlap = sum(1 for token in text_tokens if token in q_tokens)
        overlap_ratio = overlap / max(1, len(text_tokens))

        heading_tokens = set(HashingEmbeddingProvider.tokenize(heading))
        heading_boost = len(q_tokens & heading_tokens) / max(1, len(q_tokens))

        phrase_boost = 0.2 if question.lower() in text.lower() else 0.0
        return min(1.0, (overlap_ratio * 4.0) + (heading_boost * 0.4) + phrase_boost)


class HybridReranker:
    def __init__(
        self,
        *,
        backend: str,
        model_name: str,
        allow_download: bool,
    ) -> None:
        self._heuristic = HeuristicReranker()
        self._backend = backend.strip().lower()
        self._model = None

        if self._backend in {"heuristic", "none"}:
            return

        if self._backend not in {"auto", "cross-encoder", "cross_encoder", "ce"}:
            raise ValueError(f"Unsupported reranker backend: {backend}")

        try:
            sentence_transformers = importlib.import_module("sentence_transformers")
            cross_encoder_cls = getattr(sentence_transformers, "CrossEncoder")
            self._model = cross_encoder_cls(model_name, local_files_only=(not allow_download))
        except Exception as exc:  # pragma: no cover - depends on runtime model env
            if self._backend != "auto":
                raise
            _LOGGER.warning(
                "Falling back to heuristic reranking because cross-encoder initialization failed: %s",
                exc,
            )

    @staticmethod
    def _normalize_model_scores(scores: Sequence[float]) -> list[float]:
        if not scores:
            return []
        min_score = min(scores)
        max_score = max(scores)
        if min_score >= 0.0 and max_score <= 1.0:
            return [float(score) for score in scores]
        return [1.0 / (1.0 + math.exp(-float(score))) for score in scores]

    def score_many(self, question: str, texts: list[str], headings: list[str]) -> list[float]:
        heuristic_scores = [
            self._heuristic.score(question=question, text=text, heading=heading)
            for text, heading in zip(texts, headings)
        ]

        if self._model is None:
            return heuristic_scores

        pairs = [
            (question, f"{heading}\n{text}" if heading else text)
            for text, heading in zip(texts, headings)
        ]

        try:
            model_scores = self._model.predict(pairs, show_progress_bar=False)
            normalized = self._normalize_model_scores([float(score) for score in model_scores])
        except Exception as exc:  # pragma: no cover - runtime model failures are environment specific
            _LOGGER.warning(
                "Cross-encoder reranking failed; using heuristic scores only: %s",
                exc,
            )
            return heuristic_scores

        return [
            (0.8 * model_score) + (0.2 * heuristic_score)
            for model_score, heuristic_score in zip(normalized, heuristic_scores)
        ]


class HybridRetriever:
    def __init__(self, index: RagIndex, *, config: RagQueryConfig) -> None:
        self.index = index
        self.config = config
        dimensions = len(index.dense_vectors[0]) if index.dense_vectors else 256
        self.embedder = HashingEmbeddingProvider(dimensions=dimensions)
        self.reranker = HeuristicReranker()

    def search(self, question: str, *, domains: set[str], top_k: int | None = None) -> list[SearchResult]:
        if not question.strip():
            return []

        query_vector = self.embedder.embed(question)
        candidates: list[_Candidate] = []

        dense_scores: list[float] = []
        sparse_scores: list[float] = []

        for idx, chunk in enumerate(self.index.chunks):
            if domains and chunk.domain not in domains:
                continue
            dense = cosine_similarity(query_vector, self.index.dense_vectors[idx])
            sparse = self.index.bm25.score(question, idx)
            dense_scores.append(dense)
            sparse_scores.append(sparse)
            candidates.append(_Candidate(index=idx, dense=dense, sparse=sparse, combined=0.0))

        if not candidates:
            return []

        max_dense = max(dense_scores) if dense_scores else 1.0
        min_dense = min(dense_scores) if dense_scores else 0.0
        max_sparse = max(sparse_scores) if sparse_scores else 1.0

        for candidate in candidates:
            dense_norm = 0.0
            if max_dense > min_dense:
                dense_norm = (candidate.dense - min_dense) / (max_dense - min_dense)
            sparse_norm = candidate.sparse / max_sparse if max_sparse > 0 else 0.0
            candidate.combined = (
                self.config.dense_weight * dense_norm + self.config.sparse_weight * sparse_norm
            )

        candidates.sort(key=lambda c: c.combined, reverse=True)
        preselect = candidates[: max(30, (top_k or self.config.top_k) * 4)]

        results: list[SearchResult] = []
        for candidate in preselect:
            chunk = self.index.chunks[candidate.index]
            rerank = self.reranker.score(question, chunk.text, chunk.heading)
            final_score = 0.7 * candidate.combined + 0.3 * rerank
            if final_score < self.config.min_score:
                continue
            results.append(
                SearchResult(
                    chunk_id=chunk.chunk_id,
                    document_id=chunk.document_id,
                    domain=chunk.domain,
                    url=chunk.url,
                    heading=chunk.heading,
                    text=chunk.text,
                    score=final_score,
                    dense_score=candidate.dense,
                    sparse_score=candidate.sparse,
                    rerank_score=rerank,
                )
            )

        results.sort(key=lambda r: r.score, reverse=True)
        return results[: (top_k or self.config.top_k)]
