import time

from unicrawl.crawler.autoscaling.autoscale_snapshot import AutoscaleSnapshot
from unicrawl.logging.get_logger import get_logger
from unicrawl.logging.timing_config import get_timing_log_threshold_ms


class ResourceAutoscaler:
    def __init__(
        self,
        *,
        initial_concurrency: int,
        min_concurrency: int,
        monitor_interval_seconds: float,
        scale_up_step: int,
        scale_down_step: int,
    ) -> None:
        self._current_concurrency = initial_concurrency
        self._min_concurrency = min_concurrency
        self._monitor_interval_seconds = max(monitor_interval_seconds, 0.1)
        self._scale_up_step = max(scale_up_step, 1)
        self._scale_down_step = max(scale_down_step, 1)

        self._previous_sample_wall_seconds = time.monotonic()
        self._previous_processed_total: int | None = None
        self._previous_throughput: float | None = None
        self._direction = 1

    def current_concurrency(self) -> int:
        return self._current_concurrency

    def evaluate(self, processed_total: int) -> tuple[int, AutoscaleSnapshot | None, str | None]:
        logger = get_logger()
        evaluate_started_at = time.perf_counter()

        now = time.monotonic()
        interval_seconds = now - self._previous_sample_wall_seconds
        if interval_seconds < self._monitor_interval_seconds:
            evaluate_ms = (time.perf_counter() - evaluate_started_at) * 1000.0
            if evaluate_ms > get_timing_log_threshold_ms():
                logger.info(
                    "crawl.timing event=autoscaler_evaluate sampled=false evaluate_ms={:.3f} concurrency={} processed_total={} elapsed_s={:.3f} required_s={:.3f}",
                    evaluate_ms,
                    self._current_concurrency,
                    processed_total,
                    interval_seconds,
                    self._monitor_interval_seconds,
                )
            return self._current_concurrency, None, None

        reason = None
        previous = self._current_concurrency
        snapshot: AutoscaleSnapshot | None = None

        if self._previous_processed_total is None:
            self._previous_processed_total = processed_total
            self._current_concurrency = self._step_in_direction(self._direction)
            if self._current_concurrency != previous:
                reason = "throughput_bootstrap"
        else:
            interval_seconds = max(interval_seconds, 1e-9)
            processed_delta = max(processed_total - self._previous_processed_total, 0)
            throughput = processed_delta / interval_seconds
            snapshot = AutoscaleSnapshot(
                throughput_pages_per_second=throughput,
                processed_delta=processed_delta,
                interval_seconds=interval_seconds,
            )

            if self._previous_throughput is None:
                self._previous_throughput = throughput
                self._current_concurrency = self._step_in_direction(self._direction)
                if self._current_concurrency != previous:
                    reason = "throughput_probe"
            else:
                if throughput >= self._previous_throughput:
                    reason = "throughput_increased_keep_direction"
                else:
                    self._direction *= -1
                    reason = "throughput_decreased_reverse_direction"

                next_concurrency = self._step_in_direction(self._direction)
                if next_concurrency != self._current_concurrency:
                    self._current_concurrency = next_concurrency

                self._previous_throughput = throughput

            self._previous_sample_wall_seconds = now
            self._previous_processed_total = processed_total

        evaluate_ms = (time.perf_counter() - evaluate_started_at) * 1000.0
        if evaluate_ms > get_timing_log_threshold_ms():
            logger.info(
                "crawl.timing event=autoscaler_evaluate sampled=true evaluate_ms={:.3f} concurrency_before={} concurrency_after={} reason={} throughput_pps={} processed_total={}",
                evaluate_ms,
                previous,
                self._current_concurrency,
                reason if reason is not None else "none",
                f"{snapshot.throughput_pages_per_second:.3f}" if snapshot is not None else "n/a",
                processed_total,
            )
        return self._current_concurrency, snapshot, reason

    def _step_in_direction(self, direction: int) -> int:
        if direction >= 0:
            return self._clamp(self._current_concurrency + self._scale_up_step)
        return self._clamp(self._current_concurrency - self._scale_down_step)

    def _clamp(self, value: int) -> int:
        return max(self._min_concurrency, value)
