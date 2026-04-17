from dataclasses import dataclass
from pathlib import Path

@dataclass(slots=True)
class CrawlConfig:
    root_url: str
    force: bool = False
    skip_existing_pages: bool = True
    max_depth: int | None = None
    restrict_to_root_path_subtree: bool = False
    output_dir: Path | None = None
    initial_pool_size: int = 32
    autoscale_monitor_interval_seconds: float = 10.0
    autoscale_scale_up_step: int = 1
    autoscale_scale_down_step: int = 1
    request_timeout_seconds: float = 15.0
    timing_log_threshold_ms: float = 15000.0
