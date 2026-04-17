import asyncio
import time
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator
from urllib.parse import urlparse

import httpx

from unicrawl.crawler.autoscaling.resource_autoscaler import ResourceAutoscaler
from unicrawl.crawler.extract_links import extract_links
from unicrawl.crawler.fetch_page import fetch_page
from unicrawl.logging.get_logger import get_logger
from unicrawl.logging.timing_config import get_timing_log_threshold_ms, set_timing_log_threshold_ms
from unicrawl.models.crawl_config import CrawlConfig
from unicrawl.models.crawl_result import CrawlResult
from unicrawl.models.page_record import PageRecord
from unicrawl.normalization.extract_university_name import extract_university_name
from unicrawl.normalization.normalize_url import normalize_url
from unicrawl.normalization.should_skip_url import should_skip_url
from unicrawl.robots.can_fetch_url import can_fetch_url
from unicrawl.robots.load_robots_parser import load_robots_parser
from unicrawl.storage.delete_page_render_artifacts import delete_page_render_artifacts
from unicrawl.storage.delete_frontier_checkpoint import delete_frontier_checkpoint
from unicrawl.storage.frontier_checkpoint import FrontierCheckpoint
from unicrawl.storage.is_page_persisted import is_page_persisted
from unicrawl.storage.read_persisted_page_links import read_persisted_page_links
from unicrawl.storage.read_persisted_page_html import read_persisted_page_html
from unicrawl.storage.read_frontier_checkpoint import read_frontier_checkpoint
from unicrawl.storage.save_page import save_page
from unicrawl.storage.write_link_graph import write_link_graph
from unicrawl.storage.write_page_links import write_page_links
from unicrawl.storage.write_frontier_checkpoint import write_frontier_checkpoint
from unicrawl.storage.write_manifest import write_manifest


DEFAULT_REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-AU,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Upgrade-Insecure-Requests": "1",
}


async def run_crawl(config: CrawlConfig) -> CrawlResult:
    logger = get_logger()
    set_timing_log_threshold_ms(config.timing_log_threshold_ms)
    root_url = normalize_url(config.root_url)
    university_name = extract_university_name(root_url)
    output_dir = config.output_dir if config.output_dir is not None else (Path("universities") / university_name)
    output_dir.mkdir(parents=True, exist_ok=True)

    root_path_prefix = (urlparse(root_url).path or "/").rstrip("/")

    def is_in_scope(candidate_url: str) -> bool:
        root_host = (urlparse(root_url).hostname or "").lower()
        candidate_host = (urlparse(candidate_url).hostname or "").lower()

        if not root_host or not candidate_host:
            return False

        same_host = candidate_host == root_host or candidate_host.endswith(f".{root_host}")
        if not same_host:
            return False

        if not config.restrict_to_root_path_subtree:
            return True

        if root_path_prefix in {"", "/"}:
            return True

        candidate_path = (urlparse(candidate_url).path or "/").rstrip("/")
        return candidate_path == root_path_prefix or candidate_path.startswith(root_path_prefix + "/")

    autoscale_initial_pool_size = max(config.initial_pool_size, 1)
    current_concurrency = autoscale_initial_pool_size
    autoscaler = ResourceAutoscaler(
        initial_concurrency=current_concurrency,
        min_concurrency=1,
        monitor_interval_seconds=config.autoscale_monitor_interval_seconds,
        scale_up_step=config.autoscale_scale_up_step,
        scale_down_step=config.autoscale_scale_down_step,
    )
    logger.info(
        "crawl.context root_url={} output_dir={} force={} timeout_s={} mode=autoscale objective=throughput initial_pool_size={} internal_min_pool_size={} monitor_interval_s={} scale_up_step={} scale_down_step={} restrict_to_root_path_subtree={}",
        root_url,
        output_dir,
        config.force,
        config.request_timeout_seconds,
        autoscale_initial_pool_size,
        1,
        config.autoscale_monitor_interval_seconds,
        config.autoscale_scale_up_step,
        config.autoscale_scale_down_step,
        config.restrict_to_root_path_subtree,
    )

    logger.info(
        "crawl.startup step=robots_fetch status=starting root_url={} timeout_s={}",
        root_url,
        config.request_timeout_seconds,
    )
    robots_load_started_at = time.perf_counter()
    robots_parser = await load_robots_parser(root_url, timeout_seconds=config.request_timeout_seconds)
    robots_load_ms = (time.perf_counter() - robots_load_started_at) * 1000.0
    logger.info(
        "crawl.startup step=robots_fetch status={} elapsed_ms={:.3f}",
        "loaded" if robots_parser is not None else "skipped",
        robots_load_ms,
    )

    logger.info(
        "crawl.startup step=checkpoint_restore status=starting output_dir={}",
        output_dir,
    )
    checkpoint_load_started_at = time.perf_counter()
    checkpoint, checkpoint_error = read_frontier_checkpoint(output_dir, root_url)
    checkpoint_load_ms = (time.perf_counter() - checkpoint_load_started_at) * 1000.0
    if checkpoint is not None:
        queue: deque[tuple[str, int]] = deque(checkpoint.queue)
        visited: set[str] = set(checkpoint.visited)
        pages_saved = checkpoint.pages_saved
        pages_skipped = checkpoint.pages_skipped
        errors = checkpoint.errors
        logger.info(
            "crawl.resume restored saved={} skipped={} errors={} visited={} queued={} checkpoint_saved_at={} elapsed_ms={:.3f}",
            pages_saved,
            pages_skipped,
            errors,
            len(visited),
            len(queue),
            checkpoint.saved_at,
            checkpoint_load_ms,
        )
    else:
        queue = deque([(root_url, 0)])
        visited = set()
        pages_saved = 0
        pages_skipped = 0
        errors = 0
        if checkpoint_error is not None:
            logger.warning(
                "crawl.resume skipped reason={} root_url={} output_dir={} elapsed_ms={:.3f}",
                checkpoint_error,
                root_url,
                output_dir,
                checkpoint_load_ms,
            )
        else:
            logger.info(
                "crawl.startup step=checkpoint_restore status=none elapsed_ms={:.3f}",
                checkpoint_load_ms,
            )

    frontier: asyncio.Queue[tuple[str, int] | None] = asyncio.Queue()
    in_flight: dict[str, tuple[str, int]] = {}
    state_lock = asyncio.Lock()
    autoscale_lock = asyncio.Lock()
    checkpoint_lock = asyncio.Lock()

    progress_interval = 25
    next_progress_log_at = progress_interval
    checkpoint_interval = 25
    next_checkpoint_at = checkpoint_interval
    worker_tasks: list[asyncio.Task[None]] = []
    shutdown_workers = asyncio.Event()

    def log_timing(event: str, *, total_ms: float, **fields: object) -> None:
        if total_ms <= get_timing_log_threshold_ms():
            return
        fields_with_total = {"total_ms": f"{total_ms:.3f}", **fields}
        details = " ".join(f"{key}={value}" for key, value in fields_with_total.items())
        logger.info("crawl.timing event={} {}", event, details)

    @asynccontextmanager
    async def timed_lock(lock: asyncio.Lock, section: str) -> AsyncIterator[None]:
        wait_started_at = time.perf_counter()
        await lock.acquire()
        acquired_at = time.perf_counter()
        wait_ms = (acquired_at - wait_started_at) * 1000.0
        try:
            yield
        finally:
            held_ms = (time.perf_counter() - acquired_at) * 1000.0
            lock.release()
            log_timing(
                "lock",
                total_ms=wait_ms + held_ms,
                section=section,
                wait_ms=f"{wait_ms:.3f}",
                held_ms=f"{held_ms:.3f}",
            )

    if checkpoint is not None:
        for queued_url, queued_depth in queue:
            frontier.put_nowait((queued_url, queued_depth))
            normalized_queued = normalize_url(queued_url)
            if normalized_queued:
                visited.add(normalized_queued)
    else:
        visited.add(root_url)
        frontier.put_nowait((root_url, 0))

    logger.info(
        "crawl.startup step=frontier_ready queued={} visited={} restored={}",
        frontier.qsize(),
        len(visited),
        checkpoint is not None,
    )

    first_activity_logged = False

    async def snapshot_state() -> FrontierCheckpoint:
        async with timed_lock(state_lock, "snapshot_state"):
            queued_snapshot = list(frontier._queue)
            pending = [item for item in queued_snapshot if item is not None]
            queue_snapshot: list[tuple[str, int]] = [item for item in pending]
            queue_snapshot.extend(in_flight.values())
            return FrontierCheckpoint(
                root_url=root_url,
                queue=queue_snapshot,
                visited=list(visited),
                pages_saved=pages_saved,
                pages_skipped=pages_skipped,
                errors=errors,
                saved_at=datetime.now(timezone.utc).isoformat(),
            )

    async def persist_checkpoint() -> None:
        snapshot_started_at = time.perf_counter()
        checkpoint_payload = await snapshot_state()
        snapshot_ms = (time.perf_counter() - snapshot_started_at) * 1000.0

        write_started_at = time.perf_counter()
        async with timed_lock(checkpoint_lock, "checkpoint_write"):
            write_frontier_checkpoint(output_dir, checkpoint_payload)
        write_ms = (time.perf_counter() - write_started_at) * 1000.0

        log_timing(
            "checkpoint",
            total_ms=snapshot_ms + write_ms,
            snapshot_ms=f"{snapshot_ms:.3f}",
            write_ms=f"{write_ms:.3f}",
            visited=len(checkpoint_payload.visited),
            queued=len(checkpoint_payload.queue),
        )

        logger.debug(
            "crawl.checkpoint saved_at={} saved={} skipped={} errors={} visited={} queued={}",
            checkpoint_payload.saved_at,
            checkpoint_payload.pages_saved,
            checkpoint_payload.pages_skipped,
            checkpoint_payload.errors,
            len(checkpoint_payload.visited),
            len(checkpoint_payload.queue),
        )

    async def maybe_log_progress() -> None:
        nonlocal next_progress_log_at
        async with timed_lock(state_lock, "maybe_log_progress"):
            processed = pages_saved + pages_skipped + errors
            if processed < next_progress_log_at:
                return
            snapshot_saved = pages_saved
            snapshot_skipped = pages_skipped
            snapshot_errors = errors
            snapshot_visited = len(visited)
            snapshot_queued = frontier.qsize() + len(in_flight)
            snapshot_concurrency = current_concurrency
            next_progress_log_at = ((processed // progress_interval) + 1) * progress_interval
        logger.info(
            "crawl.progress saved={} skipped={} errors={} visited={} queued={} concurrency={}",
            snapshot_saved,
            snapshot_skipped,
            snapshot_errors,
            snapshot_visited,
            snapshot_queued,
            snapshot_concurrency,
        )

    async def maybe_log_first_activity(reason: str) -> None:
        nonlocal first_activity_logged
        async with timed_lock(state_lock, "maybe_log_first_activity"):
            if first_activity_logged:
                return
            first_activity_logged = True
            processed = pages_saved + pages_skipped + errors
            snapshot_queued = frontier.qsize() + len(in_flight)
            snapshot_visited = len(visited)
            snapshot_concurrency = current_concurrency
        logger.info(
            "crawl.activity status=processing reason={} processed={} queued={} visited={} concurrency={} next_progress_at={}",
            reason,
            processed,
            snapshot_queued,
            snapshot_visited,
            snapshot_concurrency,
            progress_interval,
        )

    async def maybe_checkpoint() -> None:
        nonlocal next_checkpoint_at
        should_checkpoint = False
        async with timed_lock(state_lock, "maybe_checkpoint"):
            processed = pages_saved + pages_skipped + errors
            if processed >= next_checkpoint_at:
                next_checkpoint_at = ((processed // checkpoint_interval) + 1) * checkpoint_interval
                should_checkpoint = True
        if should_checkpoint:
            await persist_checkpoint()

    async def enqueue_candidate(candidate: str, depth: int) -> bool:
        async with timed_lock(state_lock, "enqueue_candidate"):
            if candidate in visited:
                return False
            visited.add(candidate)
            frontier.put_nowait((candidate, depth))
            return True

    def collect_outgoing_links(html: str, page_url: str) -> list[str]:
        candidates: list[str] = []
        for link in extract_links(html, page_url):
            candidate = normalize_url(link)
            if not candidate:
                continue
            if not is_in_scope(candidate):
                continue
            if should_skip_url(candidate):
                continue
            candidates.append(candidate)
        return sorted(candidates)

    async def enqueue_persisted_edges(edges: list[tuple[str, str]], depth: int) -> int:
        enqueue_count = 0
        for edge_type, candidate in edges:
            target_depth = depth if edge_type == "redirect" else depth + 1
            if await enqueue_candidate(candidate, target_depth):
                enqueue_count += 1
        return enqueue_count

    def rebuild_persisted_edges(normalized_url: str) -> list[tuple[str, str]] | None:
        persisted_html = read_persisted_page_html(output_dir, normalized_url)
        if persisted_html is not None:
            persisted_links = collect_outgoing_links(persisted_html, normalized_url)
            write_page_links(output_dir, normalized_url, persisted_links)
            return [("link", link) for link in persisted_links]

        return read_persisted_page_links(output_dir, normalized_url)

    async def record_result(*, saved: int = 0, skipped: int = 0, failed: int = 0) -> None:
        nonlocal pages_saved, pages_skipped, errors
        async with timed_lock(state_lock, "record_result"):
            pages_saved += saved
            pages_skipped += skipped
            errors += failed

    async def maybe_autoscale() -> None:
        nonlocal current_concurrency
        if autoscaler is None:
            return

        processed_total = pages_saved + pages_skipped + errors

        evaluate_started_at = time.perf_counter()
        async with timed_lock(autoscale_lock, "autoscale"):
            previous = current_concurrency
            updated, snapshot, reason = autoscaler.evaluate(processed_total)
            current_concurrency = updated
            if updated > len(worker_tasks):
                for worker_id in range(len(worker_tasks), updated):
                    worker_tasks.append(asyncio.create_task(worker_loop(worker_id)))
        evaluate_ms = (time.perf_counter() - evaluate_started_at) * 1000.0
        log_timing(
            "autoscale_evaluate",
            total_ms=evaluate_ms,
            evaluate_ms=f"{evaluate_ms:.3f}",
            previous=previous,
            updated=current_concurrency,
            reason=reason if reason is not None else "none",
        )

        if snapshot is not None and current_concurrency != previous:
            logger.info(
                "crawl.autoscale from={} to={} reason={} throughput_pps={:.3f} processed_delta={} interval_s={:.3f}",
                previous,
                current_concurrency,
                reason if reason is not None else "throughput_adjusted",
                snapshot.throughput_pages_per_second,
                snapshot.processed_delta,
                snapshot.interval_seconds,
            )

    async def worker_loop(worker_id: int) -> None:
        while True:
            while not shutdown_workers.is_set() and worker_id >= current_concurrency:
                await asyncio.sleep(0.05)

            queue_wait_started_at = time.perf_counter()
            task = await frontier.get()
            queue_wait_ms = (time.perf_counter() - queue_wait_started_at) * 1000.0
            log_timing(
                "queue_wait",
                total_ms=queue_wait_ms,
                worker_id=worker_id,
                queue_wait_ms=f"{queue_wait_ms:.3f}",
                queue_depth=frontier.qsize(),
                in_flight=len(in_flight),
            )

            if task is None:
                frontier.task_done()
                return

            task_started_at = time.perf_counter()
            current_url, depth = task
            normalized_url = normalize_url(current_url)
            if not normalized_url:
                frontier.task_done()
                continue

            async with timed_lock(state_lock, "in_flight_add"):
                in_flight[normalized_url] = (current_url, depth)

            try:
                validation_started_at = time.perf_counter()
                if config.max_depth is not None and depth > config.max_depth:
                    log_timing(
                        "validation",
                        total_ms=(time.perf_counter() - validation_started_at) * 1000.0,
                        worker_id=worker_id,
                        url=normalized_url,
                        depth=depth,
                        outcome="skip",
                        reason="max_depth",
                        validation_ms=f"{(time.perf_counter() - validation_started_at) * 1000.0:.3f}",
                    )
                    await record_result(skipped=1)
                    continue
                if not is_in_scope(normalized_url):
                    log_timing(
                        "validation",
                        total_ms=(time.perf_counter() - validation_started_at) * 1000.0,
                        worker_id=worker_id,
                        url=normalized_url,
                        depth=depth,
                        outcome="skip",
                        reason="out_of_domain",
                        validation_ms=f"{(time.perf_counter() - validation_started_at) * 1000.0:.3f}",
                    )
                    await record_result(skipped=1)
                    continue
                if should_skip_url(normalized_url):
                    log_timing(
                        "validation",
                        total_ms=(time.perf_counter() - validation_started_at) * 1000.0,
                        worker_id=worker_id,
                        url=normalized_url,
                        depth=depth,
                        outcome="skip",
                        reason="policy",
                        validation_ms=f"{(time.perf_counter() - validation_started_at) * 1000.0:.3f}",
                    )
                    await record_result(skipped=1)
                    continue
                if not can_fetch_url(robots_parser, normalized_url, config.force):
                    log_timing(
                        "validation",
                        total_ms=(time.perf_counter() - validation_started_at) * 1000.0,
                        worker_id=worker_id,
                        url=normalized_url,
                        depth=depth,
                        outcome="skip",
                        reason="robots",
                        validation_ms=f"{(time.perf_counter() - validation_started_at) * 1000.0:.3f}",
                    )
                    await record_result(skipped=1)
                    continue

                log_timing(
                    "validation",
                    total_ms=(time.perf_counter() - validation_started_at) * 1000.0,
                    worker_id=worker_id,
                    url=normalized_url,
                    depth=depth,
                    outcome="pass",
                    validation_ms=f"{(time.perf_counter() - validation_started_at) * 1000.0:.3f}",
                )

                if config.skip_existing_pages and is_page_persisted(output_dir, normalized_url):
                    existing_started_at = time.perf_counter()
                    await record_result(skipped=1)
                    persisted_edges = rebuild_persisted_edges(normalized_url)
                    enqueue_started_at = time.perf_counter()
                    if persisted_edges is None:
                        persisted_edges = []
                    enqueue_count = await enqueue_persisted_edges(persisted_edges, depth)
                    enqueue_ms = (time.perf_counter() - enqueue_started_at) * 1000.0
                    log_timing(
                        "skip_existing",
                        total_ms=(time.perf_counter() - existing_started_at) * 1000.0,
                        worker_id=worker_id,
                        url=normalized_url,
                        depth=depth,
                        branch_ms=f"{(time.perf_counter() - existing_started_at) * 1000.0:.3f}",
                        enqueue_ms=f"{enqueue_ms:.3f}",
                        enqueued=enqueue_count,
                    )
                    continue

                fetch_started_at = time.perf_counter()
                fetched = await fetch_page(client, normalized_url)
                fetch_ms = (time.perf_counter() - fetch_started_at) * 1000.0
                log_timing(
                    "fetch",
                    total_ms=fetch_ms,
                    worker_id=worker_id,
                    url=normalized_url,
                    depth=depth,
                    fetch_ms=f"{fetch_ms:.3f}",
                    status="ok" if fetched is not None else "error",
                )
                if fetched is None:
                    await record_result(failed=1)
                    logger.debug("crawl.fetch_failed url={} depth={}", normalized_url, depth)
                    continue

                status_code, content_type, html, resolved_url = fetched
                resolved_normalized_url = normalize_url(resolved_url)
                if resolved_normalized_url and resolved_normalized_url != normalized_url:
                    delete_page_render_artifacts(output_dir, normalized_url)
                    write_page_links(output_dir, normalized_url, [], redirect_to=resolved_normalized_url)

                    enqueue_count = 0
                    if (
                        resolved_normalized_url
                        and is_in_scope(resolved_normalized_url)
                        and not should_skip_url(resolved_normalized_url)
                    ):
                        if await enqueue_candidate(resolved_normalized_url, depth):
                            enqueue_count = 1

                    await record_result(skipped=1)
                    continue

                if "text/html" not in content_type.lower():
                    await record_result(skipped=1)
                    logger.debug("crawl.skip_non_html url={} content_type={}", normalized_url, content_type)
                    continue

                if not html.strip():
                    delete_page_render_artifacts(output_dir, normalized_url)
                    await record_result(skipped=1)
                    logger.info(
                        "crawl.empty_html url={} status_code={} depth={}",
                        normalized_url,
                        status_code,
                        depth,
                    )
                    continue

                save_started_at = time.perf_counter()
                save_page(
                    output_dir,
                    PageRecord(
                        url=current_url,
                        normalized_url=normalized_url,
                        status_code=status_code,
                        content_type=content_type,
                        depth=depth,
                        size_bytes=len(html.encode("utf-8", errors="ignore")),
                        fetched_at=datetime.now(timezone.utc).isoformat(),
                    ),
                    html,
                )
                save_ms = (time.perf_counter() - save_started_at) * 1000.0
                log_timing(
                    "save",
                    total_ms=save_ms,
                    worker_id=worker_id,
                    url=normalized_url,
                    depth=depth,
                    save_ms=f"{save_ms:.3f}",
                    size_bytes=len(html.encode("utf-8", errors="ignore")),
                )
                await record_result(saved=1)

                outgoing_links = collect_outgoing_links(html, normalized_url)
                write_page_links(output_dir, normalized_url, outgoing_links)
                enqueue_started_at = time.perf_counter()
                enqueue_count = await enqueue_persisted_edges(
                    [("link", link) for link in outgoing_links],
                    depth,
                )
                enqueue_ms = (time.perf_counter() - enqueue_started_at) * 1000.0
                log_timing(
                    "enqueue_links",
                    total_ms=enqueue_ms,
                    worker_id=worker_id,
                    url=normalized_url,
                    depth=depth,
                    enqueue_ms=f"{enqueue_ms:.3f}",
                    enqueued=enqueue_count,
                )
            finally:
                async with timed_lock(state_lock, "in_flight_remove"):
                    in_flight.pop(normalized_url, None)
                frontier.task_done()
                log_timing(
                    "task_total",
                    total_ms=(time.perf_counter() - task_started_at) * 1000.0,
                    worker_id=worker_id,
                    url=normalized_url,
                    depth=depth,
                    task_ms=f"{(time.perf_counter() - task_started_at) * 1000.0:.3f}",
                )

            await maybe_log_first_activity("first_result_recorded")
            await maybe_log_progress()
            await maybe_checkpoint()
            await maybe_autoscale()

    try:
        async with httpx.AsyncClient(
            timeout=config.request_timeout_seconds,
            follow_redirects=True,
            headers=DEFAULT_REQUEST_HEADERS,
        ) as client:
            logger.info(
                "crawl.startup step=workers_starting workers={} queued={} progress_interval={}",
                current_concurrency,
                frontier.qsize(),
                progress_interval,
            )
            for worker_id in range(current_concurrency):
                worker_tasks.append(asyncio.create_task(worker_loop(worker_id)))

            logger.info(
                "crawl.activity status=waiting_for_first_progress queued={} concurrency={} next_progress_at={}",
                frontier.qsize(),
                current_concurrency,
                progress_interval,
            )
            await frontier.join()

            shutdown_workers.set()
            for _ in worker_tasks:
                frontier.put_nowait(None)
            await asyncio.gather(*worker_tasks)
    except asyncio.CancelledError:
        shutdown_workers.set()
        await persist_checkpoint()
        write_link_graph(output_dir, root_url)
        logger.info(
            "crawl.interrupted saved={} skipped={} errors={} visited={} queued={}",
            pages_saved,
            pages_skipped,
            errors,
            len(visited),
            frontier.qsize() + len(in_flight),
        )
        for task in worker_tasks:
            task.cancel()
        await asyncio.gather(*worker_tasks, return_exceptions=True)
        raise

    result = CrawlResult(
        university_name=university_name,
        pages_saved=pages_saved,
        pages_skipped=pages_skipped,
        errors=errors,
        output_dir=str(output_dir),
    )
    logger.info(
        "crawl.complete university={} saved={} skipped={} errors={} output={}",
        result.university_name,
        result.pages_saved,
        result.pages_skipped,
        result.errors,
        result.output_dir,
    )
    delete_frontier_checkpoint(output_dir)
    write_link_graph(output_dir, root_url)
    write_manifest(output_dir, result)
    return result
