"""University web crawler using async queue + worker pool concurrency."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from collections.abc import Callable, Coroutine
from typing import Any
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from packages.ingestion.config import IngestionSettings
from packages.ingestion.crawler.crawl_scope import CrawlScope
from packages.ingestion.extraction.models import CrawlResult
from packages.ingestion.crawler.helpers import normalize_url

logger = logging.getLogger(__name__)


class UniversityCrawler:
    """Crawl a single university domain with bounded async worker concurrency."""

    def __init__(
        self,
        *,
        university_id: uuid.UUID,
        domain: str,
        settings: IngestionSettings,
        scope: CrawlScope,
        on_page: Callable[[CrawlResult], Coroutine[Any, Any, None]],
    ) -> None:
        self._university_id = university_id
        self._domain = domain
        self._settings = settings
        self._scope = scope
        self._on_page = on_page

    async def run(self) -> int:
        """Execute crawl. Returns number of pages crawled."""
        all_urls: list[str] = []
        discovered: set[str] = set()

        seed_urls: list[str] = self._scope.seed_urls(self._domain)

        for url in seed_urls:
            normalized = normalize_url(url)
            if not normalized or normalized in discovered:
                continue
            discovered.add(normalized)
            all_urls.append(normalized)

        logger.info(
            "Crawl seed URLs for %s: %d",
            self._domain,
            len(all_urls),
        )

        if not all_urls:
            logger.warning("No URLs to crawl for %s", self._domain)
            return 0

        max_concurrency = max(self._settings.crawl_max_concurrency, 1)
        max_pages = max(self._settings.crawl_max_pages, 1)
        max_depth = max(self._settings.crawl_depth_limit, 0)

        frontier: asyncio.Queue[tuple[str, int, int] | None] = asyncio.Queue()
        seen: set[str] = set()
        state_lock = asyncio.Lock()

        pages_crawled = 0
        pages_skipped = 0

        async def record_skip(reason: str, url: str) -> None:
            nonlocal pages_skipped
            async with state_lock:
                pages_skipped += 1
            logger.debug("  x skipped (%s): %s", reason, url)

        async def can_crawl_more() -> bool:
            async with state_lock:
                return pages_crawled < max_pages

        async def record_crawled() -> int:
            nonlocal pages_crawled
            async with state_lock:
                pages_crawled += 1
                return pages_crawled

        async def enqueue_if_new(url: str, depth: int, outside_hops: int) -> bool:
            normalized = normalize_url(url)
            if not normalized:
                return False

            if not self._scope.is_under_base_domain(normalized, self._domain):
                return False

            if not self._scope.is_in_scope(normalized, self._domain):
                if outside_hops > self._scope.outside_depth:
                    return False

            async with state_lock:
                if normalized in seen:
                    return False
                seen.add(normalized)
                frontier.put_nowait((normalized, depth, outside_hops))
                return True

        for seed in all_urls:
            await enqueue_if_new(seed, 0, 0)

        async def worker_loop(client: httpx.AsyncClient) -> None:
            while True:
                task = await frontier.get()
                if task is None:
                    frontier.task_done()
                    return

                url, depth, outside_hops = task
                try:
                    if not await can_crawl_more():
                        continue

                    if depth > max_depth:
                        await record_skip("depth", url)
                        continue

                    in_scope = self._scope.is_in_scope(url, self._domain)
                    under_base = self._scope.is_under_base_domain(url, self._domain)

                    if not under_base:
                        await record_skip("outside-domain", url)
                        continue

                    if not in_scope and outside_hops > self._scope.outside_depth:
                        await record_skip("outside-scope", url)
                        continue

                    try:
                        response = await client.get(url)
                    except httpx.HTTPError:
                        await record_skip("fetch-error", url)
                        continue

                    resolved_url = normalize_url(str(response.url)) or url
                    resolved_in_scope = self._scope.is_in_scope(resolved_url, self._domain)
                    resolved_under_base = self._scope.is_under_base_domain(
                        resolved_url, self._domain
                    )

                    if not resolved_under_base:
                        await record_skip("redirect-outside-domain", resolved_url)
                        continue

                    if not resolved_in_scope and outside_hops > self._scope.outside_depth:
                        await record_skip("redirect-outside-scope", resolved_url)
                        continue

                    content_type = response.headers.get("content-type", "")
                    if "text/html" not in content_type.lower():
                        await record_skip("non-html", resolved_url)
                        continue

                    html = response.text
                    if not html.strip():
                        await record_skip("empty-html", resolved_url)
                        continue

                    content_hash = hashlib.sha256(html.encode()).hexdigest()

                    result = CrawlResult(
                        url=resolved_url,
                        html=html,
                        content_hash=content_hash,
                        etag=response.headers.get("etag"),
                        last_modified=response.headers.get("last-modified"),
                        status_code=response.status_code,
                    )
                    await self._on_page(result)

                    crawled_count = await record_crawled()

                    if crawled_count % 50 == 0:
                        logger.info(
                            "Progress: %d pages crawled, %d skipped",
                            crawled_count,
                            pages_skipped,
                        )

                    logger.info(
                        "  ok [%d] %s (%.0f KB)",
                        crawled_count,
                        resolved_url,
                        len(html) / 1024,
                    )

                    if depth >= max_depth or not await can_crawl_more():
                        continue

                    base_for_links = resolved_url
                    soup = BeautifulSoup(html, "html.parser")
                    for anchor in soup.find_all("a", href=True):
                        href = anchor.get("href")
                        if not href:
                            continue
                        candidate = urljoin(base_for_links, href)
                        candidate_norm = normalize_url(candidate)
                        if not candidate_norm:
                            continue

                        candidate_in_scope = self._scope.is_in_scope(
                            candidate_norm,
                            self._domain,
                        )
                        candidate_under_base = self._scope.is_under_base_domain(
                            candidate_norm,
                            self._domain,
                        )
                        if not candidate_under_base:
                            continue

                        child_outside_hops = 0
                        if not candidate_in_scope:
                            child_outside_hops = 1 if resolved_in_scope else outside_hops + 1
                            if child_outside_hops > self._scope.outside_depth:
                                continue

                        await enqueue_if_new(
                            candidate_norm,
                            depth + 1,
                            child_outside_hops,
                        )
                finally:
                    frontier.task_done()

        timeout = httpx.Timeout(30.0)
        headers = {"User-Agent": self._settings.crawl_user_agent}

        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers=headers,
        ) as client:
            workers = [
                asyncio.create_task(worker_loop(client))
                for _ in range(max_concurrency)
            ]

            await frontier.join()

            for _ in workers:
                frontier.put_nowait(None)
            await asyncio.gather(*workers)

        logger.info(
            "Crawl complete for %s: %d pages crawled, %d skipped (out of scope/invalid)",
            self._domain,
            pages_crawled,
            pages_skipped,
        )
        
        return pages_crawled


__all__ = ["UniversityCrawler"]
