from dataclasses import dataclass


@dataclass(slots=True)
class CrawlResult:
    university_name: str
    pages_saved: int
    pages_skipped: int
    errors: int
    output_dir: str
