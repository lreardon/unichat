from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    curated_dir: Path = Path("universities/unsw-edu-au/domains")
    embedding_backend: str = "auto"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_allow_download: bool = False
    embedding_dimensions: int = 256
    reranker_backend: str = "auto"
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    reranker_allow_download: bool = False
    chunk_size_chars: int = 1400
    chunk_overlap_chars: int = 250
    retrieval_dense_candidates: int = 120
    retrieval_sparse_candidates: int = 120
    retrieval_fused_candidates: int = 80
    retrieval_rrf_k: int = 60
    retrieval_neighbor_window: int = 1

    top_k: int = 8
    dense_weight: float = 0.65
    sparse_weight: float = 0.35
    min_score: float = 0.2

    answer_generation_backend: str = "ollama"
    answer_generation_model: str = "gemma4"
    answer_generation_base_url: str = "http://127.0.0.1:11434"
    answer_generation_timeout_s: float = 60.0
    answer_generation_temperature: float = 0.1
    answer_generation_max_tokens: int = 512
    answer_generation_context_k: int = 6
    answer_generation_max_chunk_chars: int = 1800
    answer_generation_max_evidence_chars: int = 2600
    query_upgrade_temperature: float = 0.0
    query_upgrade_max_tokens: int = 128

    model_config = SettingsConfigDict(
        env_file="backend/.env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
