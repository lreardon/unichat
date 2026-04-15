import os
import subprocess
from pathlib import Path


def read_rss_bytes() -> int | None:
    linux_statm = Path("/proc/self/statm")
    if linux_statm.exists():
        try:
            fields = linux_statm.read_text(encoding="utf-8").split()
            rss_pages = int(fields[1])
            return rss_pages * os.sysconf("SC_PAGE_SIZE")
        except (IndexError, OSError, ValueError):
            pass

    try:
        output = subprocess.check_output(["ps", "-o", "rss=", "-p", str(os.getpid())], text=True)
        rss_kib = int(output.strip())
        return rss_kib * 1024
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
