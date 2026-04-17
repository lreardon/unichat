from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class RagBuildConfig:
    university: str
    curated_dir: Path
    output_dir: Path
    chunk_size_chars: int = 1400
    chunk_overlap_chars: int = 250
    embedding_dimensions: int = 256


@dataclass(slots=True)
class RagQueryConfig:
    top_k: int = 8
    min_score: float = 0.1
    dense_weight: float = 0.55
    sparse_weight: float = 0.45
