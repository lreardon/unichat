from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from packages.ingestion.enums.page_type import PageType

@dataclass(frozen=True)
class CrawlResult:
    url: str
    html: str
    content_hash: str
    etag: str | None = None
    last_modified: str | None = None
    status_code: int = 200

    @staticmethod
    def hash_content(html: str) -> str:
        return hashlib.sha256(html.encode()).hexdigest()


@dataclass(frozen=True)
class ExtractedPage:
    url: str
    title: str
    text: str
    content_hash: str
    raw_html_path: str
    last_modified: datetime | None = None
    # page_type: PageType | None = None


@dataclass(frozen=True)
class ExtractedChunk:
    text: str
    position: int
    heading_trail: list[str]
    metadata: dict[str, Any] = field(default_factory=dict)
    token_count: int = 0
