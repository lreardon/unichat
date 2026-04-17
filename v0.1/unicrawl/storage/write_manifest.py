import json
from pathlib import Path

from unicrawl.models.crawl_result import CrawlResult


def write_manifest(base_output_dir: Path, result: CrawlResult) -> None:
    manifest_path = base_output_dir / "crawl-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "university_name": result.university_name,
                "pages_saved": result.pages_saved,
                "pages_skipped": result.pages_skipped,
                "errors": result.errors,
                "output_dir": result.output_dir,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
