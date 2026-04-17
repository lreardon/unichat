from __future__ import annotations

from pydantic import BaseModel, Field


class IngestRequest(BaseModel):
    curated_dir: str | None = None


class IngestResponse(BaseModel):
    documents: int
    chunks: int


class QueryRequest(BaseModel):
    question: str = Field(min_length=3)
    domains: list[str] = Field(default_factory=list)
    top_k: int | None = None


class Citation(BaseModel):
    source: int
    url: str
    domain: str
    heading: str
    score: float
    chunk_id: str


class QueryResponse(BaseModel):
    answer: str
    insufficient_evidence: bool
    citations: list[Citation]
    original_question: str | None = None
    upgraded_question: str | None = None


class DomainsResponse(BaseModel):
    domains: list[str]
