from dataclasses import dataclass


@dataclass(slots=True)
class DocumentRecord:
    document_id: str
    url: str
    path: str
    domain: str
    title: str


@dataclass(slots=True)
class ChunkRecord:
    chunk_id: str
    document_id: str
    domain: str
    url: str
    heading: str
    text: str
    position: int


@dataclass(slots=True)
class SearchResult:
    chunk_id: str
    document_id: str
    domain: str
    url: str
    heading: str
    text: str
    score: float
    dense_score: float
    sparse_score: float
    rerank_score: float
