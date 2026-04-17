from __future__ import annotations

import hashlib
import json
from pathlib import Path

from rag.text_extractor import extract_sections, extract_title
from rag.types import ChunkRecord, DocumentRecord


def _document_id_for_url(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


def _domain_for_path(path: str) -> str:
    first = path.split("/", 1)[0].strip()
    return first if first else "general"


def load_curated_corpus(
    curated_index_path: Path,
    *,
    chunker,
    chunk_size_chars: int,
    chunk_overlap_chars: int,
) -> tuple[list[DocumentRecord], list[ChunkRecord]]:
    if not curated_index_path.exists():
        raise FileNotFoundError(f"Missing curated index at {curated_index_path}")

    curated_dir = curated_index_path.parent
    payload = json.loads(curated_index_path.read_text(encoding="utf-8"))
    documents: list[DocumentRecord] = []
    chunks: list[ChunkRecord] = []

    for entry in payload:
        path = entry.get("path") or entry.get("filename")
        url = entry.get("url")
        if not isinstance(path, str) or not isinstance(url, str):
            continue

        html_path = curated_dir / path
        if not html_path.exists():
            continue

        html = html_path.read_text(encoding="utf-8", errors="ignore")
        document_id = _document_id_for_url(url)
        domain = _domain_for_path(path)
        title = extract_title(html)

        doc = DocumentRecord(
            document_id=document_id,
            url=url,
            path=path,
            domain=domain,
            title=title,
        )
        documents.append(doc)

        sections = extract_sections(html)
        section_chunks = chunker(
            sections,
            chunk_size_chars=chunk_size_chars,
            chunk_overlap_chars=chunk_overlap_chars,
        )
        for position, (heading, text) in enumerate(section_chunks):
            if not text.strip():
                continue
            chunk_id = f"{document_id}:{position}"
            chunks.append(
                ChunkRecord(
                    chunk_id=chunk_id,
                    document_id=document_id,
                    domain=domain,
                    url=url,
                    heading=heading,
                    text=text,
                    position=position,
                )
            )

    return documents, chunks
