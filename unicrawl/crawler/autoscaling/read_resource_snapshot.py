import time

from unicrawl.crawler.autoscaling.autoscale_snapshot import AutoscaleSnapshot
from unicrawl.logging.get_logger import get_logger
from unicrawl.logging.timing_config import get_timing_log_threshold_ms


def read_resource_snapshot(
    previous_process_seconds: float,
    previous_wall_seconds: float,
) -> tuple[AutoscaleSnapshot, float, float]:
    logger = get_logger()
    snapshot_started_at = time.perf_counter()

    current_wall_seconds = time.monotonic()
    current_process_seconds = time.process_time()

    wall_delta = max(current_wall_seconds - previous_wall_seconds, 1e-9)
    process_delta = max(current_process_seconds - previous_process_seconds, 0.0)

    snapshot = AutoscaleSnapshot(
        throughput_pages_per_second=0.0,
        processed_delta=0,
        interval_seconds=wall_delta,
    )
    snapshot_ms = (time.perf_counter() - snapshot_started_at) * 1000.0
    if snapshot_ms > get_timing_log_threshold_ms():
        logger.info(
            "crawl.timing event=read_resource_snapshot snapshot_ms={:.3f} wall_delta_s={:.6f} process_delta_s={:.6f}",
            snapshot_ms,
            wall_delta,
            process_delta,
        )

    return (
        snapshot,
        current_process_seconds,
        current_wall_seconds,
    )
