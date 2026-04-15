_timing_log_threshold_ms = 5.0


def set_timing_log_threshold_ms(value: float) -> None:
    global _timing_log_threshold_ms
    _timing_log_threshold_ms = max(float(value), 0.0)


def get_timing_log_threshold_ms() -> float:
    return _timing_log_threshold_ms
