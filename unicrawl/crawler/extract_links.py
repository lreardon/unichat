import time
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from unicrawl.logging.get_logger import get_logger
from unicrawl.logging.timing_config import get_timing_log_threshold_ms


def extract_links(html: str, base_url: str) -> set[str]:
    logger = get_logger()
    parse_started_at = time.perf_counter()
    soup = BeautifulSoup(html, "html.parser")
    parse_ms = (time.perf_counter() - parse_started_at) * 1000.0

    extract_started_at = time.perf_counter()
    links: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        links.add(urljoin(base_url, anchor["href"]))

    extract_ms = (time.perf_counter() - extract_started_at) * 1000.0
    total_ms = parse_ms + extract_ms
    if total_ms > get_timing_log_threshold_ms():
        logger.info(
            "crawl.timing event=extract_links total_ms={:.3f} base_url={} html_size={} parse_ms={:.3f} extract_ms={:.3f} links={}",
            total_ms,
            base_url,
            len(html.encode("utf-8", errors="ignore")),
            parse_ms,
            extract_ms,
            len(links),
        )
    return links
