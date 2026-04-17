import json
import time
from pathlib import Path

from unicrawl.logging.get_logger import get_logger
from unicrawl.logging.timing_config import get_timing_log_threshold_ms
from unicrawl.storage.frontier_checkpoint import FrontierCheckpoint


def write_frontier_checkpoint(base_output_dir: Path, checkpoint: FrontierCheckpoint) -> None:
    logger = get_logger()
    total_started_at = time.perf_counter()

    checkpoint_path = base_output_dir / "frontier-checkpoint.json"
    temp_path = checkpoint_path.with_suffix(".json.tmp")

    serialize_started_at = time.perf_counter()
    payload = json.dumps(
        {
            "root_url": checkpoint.root_url,
            "queue": [[url, depth] for url, depth in checkpoint.queue],
            "visited": checkpoint.visited,
            "pages_saved": checkpoint.pages_saved,
            "pages_skipped": checkpoint.pages_skipped,
            "errors": checkpoint.errors,
            "saved_at": checkpoint.saved_at,
        },
        indent=2,
    )
    serialize_ms = (time.perf_counter() - serialize_started_at) * 1000.0

    write_started_at = time.perf_counter()
    temp_path.write_text(
        payload,
        encoding="utf-8",
    )
    write_ms = (time.perf_counter() - write_started_at) * 1000.0

    replace_started_at = time.perf_counter()
    temp_path.replace(checkpoint_path)
    replace_ms = (time.perf_counter() - replace_started_at) * 1000.0

    total_ms = (time.perf_counter() - total_started_at) * 1000.0
    if total_ms > get_timing_log_threshold_ms():
        logger.info(
            "crawl.timing event=write_frontier_checkpoint queue_len={} visited={} serialize_ms={:.3f} write_ms={:.3f} replace_ms={:.3f} total_ms={:.3f}",
            len(checkpoint.queue),
            len(checkpoint.visited),
            serialize_ms,
            write_ms,
            replace_ms,
            total_ms,
        )
