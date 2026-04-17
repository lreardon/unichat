import argparse
import asyncio
import json
import sys
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from unicrawl.crawler.run_crawl import run_crawl
from unicrawl.logging.configure_logger import configure_logger
from unicrawl.logging.get_logger import get_logger
from unicrawl.models.crawl_config import CrawlConfig
from unicrawl.normalization.extract_university_name import extract_university_name
from unicrawl.normalization.normalize_url import normalize_url
from unicrawl.storage.delete_page_render_artifacts import delete_page_render_artifacts
from unicrawl.storage.frontier_checkpoint import FrontierCheckpoint
from unicrawl.storage.read_frontier_checkpoint import read_frontier_checkpoint
from unicrawl.storage.write_frontier_checkpoint import write_frontier_checkpoint
from unicrawl.storage.write_link_graph import write_link_graph


def _normalize_cli_args(argv: list[str]) -> list[str]:
    if not argv:
        return argv
    if argv[0] in {"crawl", "graph", "audit", "domains", "-h", "--help"}:
        return argv
    return ["crawl", *argv]


def _resolve_output_dir(root_url_arg: str) -> tuple[str, Path]:
    root_url = normalize_url(root_url_arg)
    if root_url is None:
        raise SystemExit(f"Invalid root URL: {root_url_arg}")

    output_dir = Path("universities") / extract_university_name(root_url)
    return root_url, output_dir


def _scan_persisted_pages_for_status(output_dir: Path, status_code: int) -> tuple[dict[str, int], set[str], int, int]:
    metadata_root = output_dir / "pages" / "by-url-hash"
    if not metadata_root.exists():
        return {}, set(), 0, 0

    matched_depths: dict[str, int] = {}
    discovered_urls: set[str] = set()
    metadata_scanned = 0
    corrupt_metadata = 0

    for metadata_path in metadata_root.glob("*/metadata.json"):
        try:
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            corrupt_metadata += 1
            continue

        normalized_url = payload.get("normalized_url")
        depth = payload.get("depth")
        current_status_code = payload.get("status_code")
        if not isinstance(normalized_url, str):
            corrupt_metadata += 1
            continue

        metadata_scanned += 1
        discovered_urls.add(normalized_url)

        if current_status_code != status_code:
            continue
        if not isinstance(depth, int):
            corrupt_metadata += 1
            continue

        previous_depth = matched_depths.get(normalized_url)
        if previous_depth is None or depth < previous_depth:
            matched_depths[normalized_url] = depth

    return matched_depths, discovered_urls, metadata_scanned, corrupt_metadata


def _read_manifest_counts(output_dir: Path, *, fallback_pages_saved: int) -> tuple[int, int, int]:
    manifest_path = output_dir / "crawl-manifest.json"
    if not manifest_path.exists():
        return fallback_pages_saved, 0, 0

    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback_pages_saved, 0, 0

    pages_saved = payload.get("pages_saved")
    pages_skipped = payload.get("pages_skipped")
    errors = payload.get("errors")
    if not isinstance(pages_saved, int) or not isinstance(pages_skipped, int) or not isinstance(errors, int):
        return fallback_pages_saved, 0, 0

    return pages_saved, pages_skipped, errors


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="unicrawl")
    subparsers = parser.add_subparsers(dest="command", required=True)

    crawl_parser = subparsers.add_parser("crawl", help="Run the crawler")
    crawl_parser.add_argument("root_url")
    crawl_parser.add_argument("--force", action="store_true", help="Bypass robots.txt checks")
    crawl_parser.add_argument(
        "--timing-threshold-ms",
        type=float,
        default=None,
        help="Log timing events only when they exceed this duration in milliseconds",
    )

    graph_parser = subparsers.add_parser("graph", help="Regenerate graph artifacts from persisted crawl data")
    graph_parser.add_argument("root_url")

    audit_parser = subparsers.add_parser(
        "audit",
        help="Requeue persisted 202 pages into the frontier checkpoint for refetch",
    )
    audit_parser.add_argument("root_url")

    domains_parser = subparsers.add_parser(
        "domains",
        help="Crawl each domain subtree from its domain root URL",
    )
    domains_parser.add_argument(
        "domains_dir",
        nargs="?",
        default="universities/unsw-edu-au/domains",
        help="Directory containing domains/index.json",
    )
    domains_parser.add_argument("--force", action="store_true", help="Bypass robots.txt checks")
    domains_parser.add_argument(
        "--timing-threshold-ms",
        type=float,
        default=None,
        help="Log timing events only when they exceed this duration in milliseconds",
    )
    domains_parser.add_argument(
        "--output-root",
        default=None,
        help="Root directory for per-domain crawl outputs (default: universities/<host>/domain-crawls)",
    )
    domains_parser.add_argument(
        "--only",
        nargs="*",
        default=None,
        help="Optional subset of domain slugs to crawl (e.g., engineering science)",
    )

    return parser


def _domain_slug_from_path(path: str) -> str | None:
    parts = [part for part in path.split("/") if part]
    if not parts:
        return None
    return parts[0]


def _domain_root_from_entry_url(entry_url: str, domain_slug: str) -> str | None:
    normalized = normalize_url(entry_url)
    if normalized is None:
        return None

    parsed = urlparse(normalized)
    if not parsed.scheme or not parsed.netloc:
        return None

    return urlunparse((parsed.scheme, parsed.netloc, f"/{domain_slug}", "", "", ""))


def _load_domain_roots(domains_dir: Path) -> list[tuple[str, str]]:
    index_path = domains_dir / "index.json"
    if not index_path.exists():
        raise SystemExit(f"Missing domains index at {index_path}")

    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Could not parse domains index {index_path}: {exc}")

    if not isinstance(payload, list):
        raise SystemExit(f"Domains index must be a JSON array: {index_path}")

    roots_by_slug: OrderedDict[str, str] = OrderedDict()
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        path_value = entry.get("path")
        if not isinstance(path_value, str):
            continue

        domain_slug = _domain_slug_from_path(path_value)
        if not domain_slug or domain_slug in roots_by_slug:
            continue

        entry_url = entry.get("final_url") if isinstance(entry.get("final_url"), str) else entry.get("url")
        if not isinstance(entry_url, str):
            continue

        root_url = _domain_root_from_entry_url(entry_url, domain_slug)
        if root_url is None:
            continue

        roots_by_slug[domain_slug] = root_url

    if not roots_by_slug:
        raise SystemExit(f"No domain roots discovered from {index_path}")

    return list(roots_by_slug.items())


def _is_in_root_subtree(root_url: str, candidate_url: str) -> bool:
    root_parsed = urlparse(root_url)
    candidate_parsed = urlparse(candidate_url)

    root_host = (root_parsed.hostname or "").lower()
    candidate_host = (candidate_parsed.hostname or "").lower()
    if not root_host or not candidate_host:
        return False
    if not (candidate_host == root_host or candidate_host.endswith(f".{root_host}")):
        return False

    root_prefix = (root_parsed.path or "/").rstrip("/")
    if root_prefix in {"", "/"}:
        return True

    candidate_path = (candidate_parsed.path or "/").rstrip("/")
    return candidate_path == root_prefix or candidate_path.startswith(root_prefix + "/")


def _collect_subtree_urls(output_dir: Path, root_url: str) -> list[str]:
    metadata_root = output_dir / "pages" / "by-url-hash"
    if not metadata_root.exists():
        return []

    collected: set[str] = set()
    for metadata_path in metadata_root.glob("*/metadata.json"):
        try:
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        normalized_url = payload.get("normalized_url")
        if not isinstance(normalized_url, str):
            continue
        if _is_in_root_subtree(root_url, normalized_url):
            collected.add(normalized_url)

    return sorted(collected)


def _run_domains_command(args: argparse.Namespace) -> None:
    logger = get_logger()
    domains_dir = Path(args.domains_dir)
    domain_roots = _load_domain_roots(domains_dir)

    if args.only:
        selected = set(args.only)
        domain_roots = [(slug, root_url) for slug, root_url in domain_roots if slug in selected]

    if not domain_roots:
        raise SystemExit("No domains selected for crawling")

    default_host = extract_university_name(domain_roots[0][1])
    output_root = Path(args.output_root) if args.output_root else (Path("universities") / default_host / "domain-crawls")
    output_root.mkdir(parents=True, exist_ok=True)

    logger.info(
        "domains.start domains_dir={} domains={} output_root={} force={} timing_threshold_ms={}",
        domains_dir,
        len(domain_roots),
        output_root,
        args.force,
        args.timing_threshold_ms,
    )

    manifest_entries: list[dict[str, object]] = []
    for index, (domain_slug, root_url) in enumerate(domain_roots, start=1):
        domain_output_dir = output_root / domain_slug
        crawl_config = CrawlConfig(
            root_url=root_url,
            force=args.force,
            restrict_to_root_path_subtree=True,
            output_dir=domain_output_dir,
        )
        if args.timing_threshold_ms is not None:
            crawl_config.timing_log_threshold_ms = args.timing_threshold_ms

        logger.info(
            "domains.crawl.start index={} total={} domain={} root_url={} output_dir={}",
            index,
            len(domain_roots),
            domain_slug,
            root_url,
            domain_output_dir,
        )

        try:
            result = asyncio.run(run_crawl(crawl_config))
        except KeyboardInterrupt:
            logger.info("domains.stopped reason=keyboard_interrupt domain={} root_url={}", domain_slug, root_url)
            return

        collected_urls = _collect_subtree_urls(domain_output_dir, root_url)
        urls_path = domain_output_dir / "subtree-urls.txt"
        urls_path.write_text("\n".join(collected_urls) + ("\n" if collected_urls else ""), encoding="utf-8")

        logger.info(
            "domains.crawl.done index={} total={} domain={} root_url={} saved={} skipped={} errors={} collected_urls={} urls_path={}",
            index,
            len(domain_roots),
            domain_slug,
            root_url,
            result.pages_saved,
            result.pages_skipped,
            result.errors,
            len(collected_urls),
            urls_path,
        )

        manifest_entries.append(
            {
                "domain": domain_slug,
                "root_url": root_url,
                "output_dir": str(domain_output_dir),
                "pages_saved": result.pages_saved,
                "pages_skipped": result.pages_skipped,
                "errors": result.errors,
                "collected_urls": len(collected_urls),
                "collected_urls_path": str(urls_path),
            }
        )

    manifest_path = output_root / "domain-crawl-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "domains": manifest_entries,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    logger.info(
        "domains.done domains={} output_root={} manifest={}",
        len(manifest_entries),
        output_root,
        manifest_path,
    )


def _run_crawl_command(args: argparse.Namespace) -> None:
    logger = get_logger()

    crawl_config = CrawlConfig(root_url=args.root_url, force=args.force)
    if args.timing_threshold_ms is not None:
        crawl_config.timing_log_threshold_ms = args.timing_threshold_ms

    logger.info(
        "crawl.start root_url={} force={} timing_threshold_ms={}",
        args.root_url,
        args.force,
        crawl_config.timing_log_threshold_ms,
    )
    try:
        result = asyncio.run(run_crawl(crawl_config))
    except KeyboardInterrupt:
        logger.info("crawl.stopped reason=keyboard_interrupt")
        return

    logger.info(
        "crawl.done saved={} skipped={} errors={} output={}",
        result.pages_saved,
        result.pages_skipped,
        result.errors,
        result.output_dir,
    )


def _run_graph_command(args: argparse.Namespace) -> None:
    logger = get_logger()

    root_url, output_dir = _resolve_output_dir(args.root_url)
    if not output_dir.exists():
        raise SystemExit(f"No crawl output found for {root_url} at {output_dir}")

    write_link_graph(output_dir, root_url)
    logger.info("graph.done root_url={} output={}", root_url, output_dir)


def _run_audit_command(args: argparse.Namespace) -> None:
    logger = get_logger()

    root_url, output_dir = _resolve_output_dir(args.root_url)
    if not output_dir.exists():
        raise SystemExit(f"No crawl output found for {root_url} at {output_dir}")

    target_status_code = 202
    logger.info(
        "audit.start root_url={} output_dir={} status_code={}",
        root_url,
        output_dir,
        target_status_code,
    )

    matched_depths, discovered_urls, metadata_scanned, corrupt_metadata = _scan_persisted_pages_for_status(
        output_dir,
        target_status_code,
    )
    if not matched_depths:
        logger.info(
            "audit.done root_url={} status_code={} matches=0 metadata_scanned={} corrupt_metadata={} frontier_queued=0",
            root_url,
            target_status_code,
            metadata_scanned,
            corrupt_metadata,
        )
        return

    checkpoint, checkpoint_error = read_frontier_checkpoint(output_dir, root_url)
    if checkpoint is not None:
        queue = list(checkpoint.queue)
        visited = set(checkpoint.visited)
        pages_saved = checkpoint.pages_saved
        pages_skipped = checkpoint.pages_skipped
        errors = checkpoint.errors
        checkpoint_status = "updated"
    else:
        pages_saved, pages_skipped, errors = _read_manifest_counts(
            output_dir,
            fallback_pages_saved=metadata_scanned,
        )
        queue = []
        visited = set(discovered_urls)
        checkpoint_status = "created"
        if checkpoint_error is not None:
            logger.warning(
                "audit.checkpoint skipped reason={} root_url={} output_dir={}",
                checkpoint_error,
                root_url,
                output_dir,
            )

    visited.add(root_url)
    queued_urls = {
        normalized_url
        for queued_url, _ in queue
        for normalized_url in [normalize_url(queued_url)]
        if normalized_url is not None
    }

    requeued = 0
    already_queued = 0
    deleted_artifacts = 0
    for normalized_url, depth in sorted(matched_depths.items()):
        delete_page_render_artifacts(output_dir, normalized_url)
        deleted_artifacts += 1
        if normalized_url in queued_urls:
            already_queued += 1
            continue

        queue.append((normalized_url, depth))
        queued_urls.add(normalized_url)
        requeued += 1

    if requeued > 0 or checkpoint is None:
        write_frontier_checkpoint(
            output_dir,
            FrontierCheckpoint(
                root_url=root_url,
                queue=queue,
                visited=sorted(visited),
                pages_saved=pages_saved,
                pages_skipped=pages_skipped,
                errors=errors,
                saved_at=datetime.now(timezone.utc).isoformat(),
            ),
        )
    else:
        checkpoint_status = "unchanged"

    logger.info(
        "audit.done root_url={} status_code={} matches={} requeued={} already_queued={} deleted_artifacts={} metadata_scanned={} corrupt_metadata={} checkpoint={} frontier_queued={} visited={}",
        root_url,
        target_status_code,
        len(matched_depths),
        requeued,
        already_queued,
        deleted_artifacts,
        metadata_scanned,
        corrupt_metadata,
        checkpoint_status,
        len(queue),
        len(visited),
    )


def main() -> None:
    configure_logger()
    parser = _build_parser()
    args = parser.parse_args(_normalize_cli_args(sys.argv[1:]))

    if args.command == "crawl":
        _run_crawl_command(args)
        return

    if args.command == "graph":
        _run_graph_command(args)
        return

    if args.command == "audit":
        _run_audit_command(args)
        return

    if args.command == "domains":
        _run_domains_command(args)
        return

    raise SystemExit(f"Unsupported command: {args.command}")
