from __future__ import annotations

import uuid
from pathlib import Path


class RawHTMLStore:
    """Persist raw HTML to local filesystem at data/raw/{university_id}/{content_hash}.html."""

    def __init__(self, base_path: str = "data/raw") -> None:
        self._base = Path(base_path)

    def save(self, university_id: uuid.UUID, content_hash: str, html: str) -> str:
        """Write HTML to disk. Returns the relative path."""
        dir_path = self._base / str(university_id)
        dir_path.mkdir(parents=True, exist_ok=True)
        file_path = dir_path / f"{content_hash}.html"
        file_path.write_text(html, encoding="utf-8")
        return str(file_path)

    def load(self, path: str) -> str:
        """Read HTML from disk."""
        return Path(path).read_text(encoding="utf-8")

    def exists(self, university_id: uuid.UUID, content_hash: str) -> bool:
        file_path = self._base / str(university_id) / f"{content_hash}.html"
        return file_path.exists()
