from dataclasses import dataclass


@dataclass(slots=True)
class AutoscaleSnapshot:
    throughput_pages_per_second: float
    processed_delta: int
    interval_seconds: float
