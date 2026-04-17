import json
import time
from pathlib import Path

from unicrawl.logging.get_logger import get_logger
from unicrawl.logging.timing_config import get_timing_log_threshold_ms
from unicrawl.models.page_record import PageRecord
from unicrawl.storage.url_hash_for_normalized_url import url_hash_for_normalized_url


def save_page(base_output_dir: Path, record: PageRecord, html: str) -> str:
    logger = get_logger()
    total_started_at = time.perf_counter()

    url_hash = url_hash_for_normalized_url(record.normalized_url)
    page_dir = base_output_dir / "pages" / "by-url-hash" / url_hash

    mkdir_started_at = time.perf_counter()
    page_dir.mkdir(parents=True, exist_ok=True)
    mkdir_ms = (time.perf_counter() - mkdir_started_at) * 1000.0

    html_write_started_at = time.perf_counter()
    (page_dir / "page.html").write_text(html, encoding="utf-8", errors="ignore")
    html_write_ms = (time.perf_counter() - html_write_started_at) * 1000.0

    normalized_write_started_at = time.perf_counter()
    (page_dir / "normalized-url.txt").write_text(record.normalized_url, encoding="utf-8")
    normalized_write_ms = (time.perf_counter() - normalized_write_started_at) * 1000.0

    metadata_write_started_at = time.perf_counter()
    (page_dir / "metadata.json").write_text(
        json.dumps(
            {
                "url": record.url,
                "normalized_url": record.normalized_url,
                "status_code": record.status_code,
                "content_type": record.content_type,
                "depth": record.depth,
                "size_bytes": record.size_bytes,
                "fetched_at": record.fetched_at,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    metadata_write_ms = (time.perf_counter() - metadata_write_started_at) * 1000.0
    total_ms = (time.perf_counter() - total_started_at) * 1000.0
    if total_ms > get_timing_log_threshold_ms():
        logger.info(
            "crawl.timing event=save_page url={} depth={} size_bytes={} mkdir_ms={:.3f} html_write_ms={:.3f} normalized_write_ms={:.3f} metadata_write_ms={:.3f} total_ms={:.3f}",
            record.normalized_url,
            record.depth,
            record.size_bytes,
            mkdir_ms,
            html_write_ms,
            normalized_write_ms,
            metadata_write_ms,
            total_ms,
        )

    return url_hash
