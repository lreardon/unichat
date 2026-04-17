from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
import re

from sqlalchemy import String, bindparam, delete, distinct, func, select, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Session

from app.answer_generation import build_answer_generator, build_query_upgrader
from app.models import Chunk, Document
from app.settings import settings
from rag.chunker import chunk_sections
from rag.config import RagQueryConfig
from rag.corpus import load_curated_corpus
from rag.embedding import build_embedding_provider
from rag.retriever import HybridReranker
from rag.types import SearchResult


_embedder = build_embedding_provider(
    backend=settings.embedding_backend,
    dimensions=settings.embedding_dimensions,
    model_name=settings.embedding_model,
    allow_download=settings.embedding_allow_download,
)
_reranker = HybridReranker(
    backend=settings.reranker_backend,
    model_name=settings.reranker_model,
    allow_download=settings.reranker_allow_download,
)
_query_config = RagQueryConfig(
    top_k=settings.top_k,
    min_score=settings.min_score,
    dense_weight=settings.dense_weight,
    sparse_weight=settings.sparse_weight,
)
_answer_generator = build_answer_generator()
_query_upgrader = build_query_upgrader()
_PROCESS_QUERY_RE = re.compile(
    r"\b(step|steps|stage|stages|process|how\s+to\s+apply|application\s+guide|application\s+process|guide)\b",
    re.IGNORECASE,
)
_PROCESS_HEADING_RE = re.compile(r"\b(step|stage|application|process|how to apply|guide)\b", re.IGNORECASE)


@dataclass(slots=True)
class _RankedCandidate:
    chunk_id: str
    document_id: str
    domain: str
    url: str
    heading: str
    text: str
    position: int
    dense_score: float = 0.0
    sparse_score: float = 0.0
    dense_rank: int | None = None
    sparse_rank: int | None = None
    fused_score: float = 0.0
    fused_norm: float = 0.0


def _is_process_question(question: str) -> bool:
    return _PROCESS_QUERY_RE.search(question) is not None


def _expanded_sparse_query(question: str, is_process: bool) -> str:
    if not is_process:
        return question
    return f"{question} steps stage process application guide how to apply"


def _rrf(rank: int | None, *, k: int) -> float:
    if rank is None:
        return 0.0
    return 1.0 / (k + rank)


def _load_dense_candidates(
    session: Session,
    *,
    query_vector_literal: str,
    domains: list[str],
    candidate_limit: int,
) -> list[dict[str, object]]:
    statement = text(
        """
        SELECT
          c.chunk_id,
          c.document_id,
          c.domain,
          c.url,
          c.heading,
          c.text,
          c.position,
          (1 - (c.embedding <=> CAST(:query_vector AS vector))) AS dense_score
        FROM chunks c
        WHERE (:domain_count = 0 OR c.domain = ANY(:domains))
        ORDER BY c.embedding <=> CAST(:query_vector AS vector) ASC
        LIMIT :candidate_limit
        """
    ).bindparams(bindparam("domains", type_=ARRAY(String())))
    return list(
        session.execute(
            statement,
            {
                "query_vector": query_vector_literal,
                "domain_count": len(domains),
                "domains": domains,
                "candidate_limit": candidate_limit,
            },
        )
        .mappings()
        .all()
    )


def _load_sparse_candidates(
    session: Session,
    *,
    sparse_query: str,
    domains: list[str],
    candidate_limit: int,
) -> list[dict[str, object]]:
    statement = text(
        """
        SELECT
          c.chunk_id,
          c.document_id,
          c.domain,
          c.url,
          c.heading,
          c.text,
          c.position,
          ts_rank_cd(to_tsvector('english', c.text), plainto_tsquery('english', :sparse_query)) AS sparse_score
        FROM chunks c
        WHERE (:domain_count = 0 OR c.domain = ANY(:domains))
        ORDER BY sparse_score DESC, c.document_id ASC, c.position ASC
        LIMIT :candidate_limit
        """
    ).bindparams(bindparam("domains", type_=ARRAY(String())))
    return list(
        session.execute(
            statement,
            {
                "sparse_query": sparse_query,
                "domain_count": len(domains),
                "domains": domains,
                "candidate_limit": candidate_limit,
            },
        )
        .mappings()
        .all()
    )


def _fuse_candidates(
    dense_rows: list[dict[str, object]],
    sparse_rows: list[dict[str, object]],
    *,
    is_process: bool,
) -> list[_RankedCandidate]:
    by_chunk_id: dict[str, _RankedCandidate] = {}

    for rank, row in enumerate(dense_rows, start=1):
        chunk_id = str(row["chunk_id"])
        candidate = by_chunk_id.get(chunk_id)
        if candidate is None:
            candidate = _RankedCandidate(
                chunk_id=chunk_id,
                document_id=str(row["document_id"]),
                domain=str(row["domain"]),
                url=str(row["url"]),
                heading=str(row["heading"]),
                text=str(row["text"]),
                position=int(row["position"]),
            )
            by_chunk_id[chunk_id] = candidate
        candidate.dense_rank = rank
        candidate.dense_score = float(row["dense_score"] or 0.0)

    for rank, row in enumerate(sparse_rows, start=1):
        chunk_id = str(row["chunk_id"])
        candidate = by_chunk_id.get(chunk_id)
        if candidate is None:
            candidate = _RankedCandidate(
                chunk_id=chunk_id,
                document_id=str(row["document_id"]),
                domain=str(row["domain"]),
                url=str(row["url"]),
                heading=str(row["heading"]),
                text=str(row["text"]),
                position=int(row["position"]),
            )
            by_chunk_id[chunk_id] = candidate
        candidate.sparse_rank = rank
        candidate.sparse_score = float(row["sparse_score"] or 0.0)

    if not by_chunk_id:
        return []

    for candidate in by_chunk_id.values():
        intent_bonus = 0.05 if (is_process and _PROCESS_HEADING_RE.search(candidate.heading)) else 0.0
        candidate.fused_score = (
            _rrf(candidate.dense_rank, k=settings.retrieval_rrf_k)
            + _rrf(candidate.sparse_rank, k=settings.retrieval_rrf_k)
            + intent_bonus
        )

    ordered = sorted(by_chunk_id.values(), key=lambda item: item.fused_score, reverse=True)
    max_score = max(item.fused_score for item in ordered)
    min_score = min(item.fused_score for item in ordered)
    if max_score > min_score:
        for item in ordered:
            item.fused_norm = (item.fused_score - min_score) / (max_score - min_score)
    else:
        for item in ordered:
            item.fused_norm = 1.0
    return ordered


def _expand_context(
    session: Session,
    *,
    candidates: list[_RankedCandidate],
    window: int,
) -> dict[str, str]:
    if window <= 0:
        return {candidate.chunk_id: candidate.text for candidate in candidates}

    expanded: dict[str, str] = {}
    for candidate in candidates:
        start = max(0, candidate.position - window)
        end = candidate.position + window
        rows = session.execute(
            select(Chunk.position, Chunk.text)
            .where(
                Chunk.document_id == candidate.document_id,
                Chunk.position >= start,
                Chunk.position <= end,
            )
            .order_by(Chunk.position.asc())
        ).all()

        parts = [str(chunk_text).strip() for _, chunk_text in rows if str(chunk_text).strip()]
        expanded[candidate.chunk_id] = "\n".join(parts) if parts else candidate.text
    return expanded


def ingest_curated(session: Session, curated_dir_override: str | None = None) -> tuple[int, int]:
    if curated_dir_override:
        override_path = Path(curated_dir_override)
        curated_index_path = (
            override_path if override_path.suffix.lower() == ".json" else override_path / "index.json"
        )
    else:
        curated_index_path = settings.curated_dir / "index.json"

    documents, chunks = load_curated_corpus(
        curated_index_path,
        chunker=chunk_sections,
        chunk_size_chars=settings.chunk_size_chars,
        chunk_overlap_chars=settings.chunk_overlap_chars,
    )
    document_ids = [doc.document_id for doc in documents]

    for doc in documents:
        session.merge(
            Document(
                document_id=doc.document_id,
                url=doc.url,
                path=doc.path,
                domain=doc.domain,
                title=doc.title,
            )
        )

    if document_ids:
        session.execute(delete(Chunk).where(Chunk.document_id.in_(document_ids)))

    for chunk in chunks:
        session.merge(
            Chunk(
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                domain=chunk.domain,
                url=chunk.url,
                heading=chunk.heading,
                text=chunk.text,
                position=chunk.position,
                embedding=_embedder.embed(chunk.text),
            )
        )

    session.commit()
    return len(documents), len(chunks)


def list_domains(session: Session) -> list[str]:
    rows = session.execute(select(distinct(Document.domain)).order_by(Document.domain)).all()
    return [row[0] for row in rows if row[0]]


def query(session: Session, question: str, domains: list[str], top_k: int | None = None) -> dict[str, object]:
    upgraded_question = _query_upgrader.upgrade(question, domains)
    candidates = _retrieve_candidates(session, question=upgraded_question, domains=domains, top_k=top_k)
    payload = _answer_generator.generate(question, candidates)
    payload["original_question"] = question
    payload["upgraded_question"] = upgraded_question
    return payload


def query_stream(
    session: Session,
    question: str,
    domains: list[str],
    top_k: int | None = None,
) -> Iterator[dict[str, object]]:
    upgraded_question = _query_upgrader.upgrade(question, domains)

    yield {
        "type": "query_upgrade",
        "original_question": question,
        "upgraded_question": upgraded_question,
        "system_prompt": _query_upgrader.system_prompt_for_debug(),
    }

    candidates = _retrieve_candidates(session, question=upgraded_question, domains=domains, top_k=top_k)

    yield {
        "type": "retrieval",
        "documents": [
            {
                "rank": idx,
                "url": result.url,
                "domain": result.domain,
                "heading": result.heading,
                "text": result.text,
                "score": round(result.score, 4),
                "chunk_id": result.chunk_id,
            }
            for idx, result in enumerate(candidates, start=1)
        ],
    }
    yield {
        "type": "prompt",
        "system_prompt": _answer_generator.system_prompt_for_debug(),
    }

    for event in _answer_generator.stream_generate(question, candidates):
        if event.get("type") == "final":
            event["original_question"] = question
            event["upgraded_question"] = upgraded_question
        yield event


def _retrieve_candidates(
    session: Session,
    *,
    question: str,
    domains: list[str],
    top_k: int | None = None,
) -> list[SearchResult]:
    query_vector = _embedder.embed(question)
    query_vector_literal = "[" + ",".join(f"{value:.8f}" for value in query_vector) + "]"
    is_process = _is_process_question(question)
    sparse_query = _expanded_sparse_query(question, is_process)
    result_limit = top_k or _query_config.top_k

    dense_limit = max(settings.retrieval_dense_candidates, result_limit * 8)
    sparse_limit = max(settings.retrieval_sparse_candidates, result_limit * 8)
    fused_limit = max(settings.retrieval_fused_candidates, result_limit * 6)

    dense_rows = _load_dense_candidates(
        session,
        query_vector_literal=query_vector_literal,
        domains=domains,
        candidate_limit=dense_limit,
    )
    sparse_rows = _load_sparse_candidates(
        session,
        sparse_query=sparse_query,
        domains=domains,
        candidate_limit=sparse_limit,
    )

    fused_candidates = _fuse_candidates(dense_rows, sparse_rows, is_process=is_process)
    if not fused_candidates:
        return []

    preselected = fused_candidates[:fused_limit]
    expanded_context = _expand_context(
        session,
        candidates=preselected,
        window=settings.retrieval_neighbor_window,
    )

    rerank_scores = _reranker.score_many(
        question,
        [expanded_context[candidate.chunk_id] for candidate in preselected],
        [candidate.heading for candidate in preselected],
    )

    candidates: list[SearchResult] = []
    for candidate, rerank_score in zip(preselected, rerank_scores):
        final_score = (0.55 * candidate.fused_norm) + (0.45 * rerank_score)
        if final_score < _query_config.min_score:
            continue
        candidates.append(
            SearchResult(
                chunk_id=candidate.chunk_id,
                document_id=candidate.document_id,
                domain=candidate.domain,
                url=candidate.url,
                heading=candidate.heading,
                text=expanded_context[candidate.chunk_id],
                score=final_score,
                dense_score=candidate.dense_score,
                sparse_score=candidate.sparse_score,
                rerank_score=rerank_score,
            )
        )

    candidates.sort(key=lambda item: item.score, reverse=True)
    return candidates[:result_limit]


def health_summary(session: Session) -> dict[str, int]:
    doc_count = session.scalar(select(func.count()).select_from(Document)) or 0
    chunk_count = session.scalar(select(func.count()).select_from(Chunk)) or 0
    return {"documents": int(doc_count), "chunks": int(chunk_count)}


def answer_generation_health() -> dict[str, object]:
    return _answer_generator.health_status()
