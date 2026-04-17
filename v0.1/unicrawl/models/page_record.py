from dataclasses import dataclass


@dataclass(slots=True)
class PageRecord:
    url: str
    normalized_url: str
    status_code: int
    content_type: str
    depth: int
    size_bytes: int
    fetched_at: str
