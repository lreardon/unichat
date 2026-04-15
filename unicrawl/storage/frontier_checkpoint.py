from dataclasses import dataclass


@dataclass(slots=True)
class FrontierCheckpoint:
    root_url: str
    queue: list[tuple[str, int]]
    visited: list[str]
    pages_saved: int
    pages_skipped: int
    errors: int
    saved_at: str
