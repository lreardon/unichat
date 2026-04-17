from __future__ import annotations

import json
from pathlib import Path

from rag.bm25 import BM25Index
from rag.embedding import HashingEmbeddingProvider
from rag.types import ChunkRecord, DocumentRecord


class RagIndex:
    def __init__(
        self,
        *,
        documents: list[DocumentRecord],
        chunks: list[ChunkRecord],
        dense_vectors: list[list[float]],
        bm25: BM25Index,
    ) -> None:
        self.documents = documents
        self.chunks = chunks
        self.dense_vectors = dense_vectors
        self.bm25 = bm25
        self.document_by_id = {doc.document_id: doc for doc in documents}
        self.available_domains = sorted({chunk.domain for chunk in chunks})

    def save(self, output_dir: Path) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        target = output_dir / "index.json"
        payload = {
            "documents": [doc.__dict__ for doc in self.documents],
            "chunks": [chunk.__dict__ for chunk in self.chunks],
            "dense_vectors": self.dense_vectors,
            "bm25": {
                "k1": self.bm25.k1,
                "b": self.bm25.b,
                "avg_doc_len": self.bm25.avg_doc_len,
                "doc_freqs": self.bm25.doc_freqs,
                "term_freqs": self.bm25.term_freqs,
                "doc_lengths": self.bm25.doc_lengths,
            },
        }
        target.write_text(json.dumps(payload), encoding="utf-8")
        return target

    @classmethod
    def load(cls, index_path: Path) -> "RagIndex":
        payload = json.loads(index_path.read_text(encoding="utf-8"))

        documents = [DocumentRecord(**item) for item in payload["documents"]]
        chunks = [ChunkRecord(**item) for item in payload["chunks"]]
        dense_vectors = payload["dense_vectors"]

        bm25_payload = payload["bm25"]
        bm25 = BM25Index(k1=bm25_payload.get("k1", 1.5), b=bm25_payload.get("b", 0.75))
        bm25.avg_doc_len = bm25_payload.get("avg_doc_len", 0.0)
        bm25.doc_freqs = {str(k): int(v) for k, v in bm25_payload.get("doc_freqs", {}).items()}
        bm25.term_freqs = [
            {str(k): int(v) for k, v in item.items()} for item in bm25_payload.get("term_freqs", [])
        ]
        bm25.doc_lengths = [int(v) for v in bm25_payload.get("doc_lengths", [])]

        return cls(documents=documents, chunks=chunks, dense_vectors=dense_vectors, bm25=bm25)


def build_index(documents: list[DocumentRecord], chunks: list[ChunkRecord], *, dimensions: int) -> RagIndex:
    embedder = HashingEmbeddingProvider(dimensions=dimensions)
    dense_vectors = [embedder.embed(chunk.text) for chunk in chunks]
    bm25 = BM25Index()
    bm25.build([chunk.text for chunk in chunks])
    return RagIndex(documents=documents, chunks=chunks, dense_vectors=dense_vectors, bm25=bm25)
